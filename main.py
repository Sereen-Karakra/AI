import math
import random
import time
import copy
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, Toplevel, Text

# --- constants ---
SHOP_LOCATION = (0, 0)
X_RANGE = (0, 100)
Y_RANGE = (0, 100)

# sa defaults
SA_INITIAL_TEMP = 1000.0
SA_COOLING_RATE_DEFAULT = 0.95  # user choice between 0.90 and 0.99
SA_STOPPING_TEMP = 1.0
SA_ITERATIONS_PER_TEMP = 100

# ga defaults
GA_POPULATION_SIZE_DEFAULT = 75  # user choice between 50 and 100
GA_MUTATION_RATE_DEFAULT = 0.05  # user choice between 0.01 and 0.1
GA_NUM_GENERATIONS = 500
GA_TOURNAMENT_SIZE = 5  # parameter for tournament selection


# --- data structures ---

class Package:
    """represents a package to be delivered."""

    def __init__(self, id, location, weight, priority):
        if not (X_RANGE[0] <= location[0] <= X_RANGE[1] and
                Y_RANGE[0] <= location[1] <= Y_RANGE[1]):
            raise ValueError(
                f"package {id} location {location} out of range [{X_RANGE[0]}-{X_RANGE[1]}],[{Y_RANGE[0]}-{Y_RANGE[1]}].")
        if weight <= 0:
            raise ValueError(f"package {id} weight ({weight}) must be positive.")
        if not (1 <= priority <= 5):
            raise ValueError(f"package {id} priority ({priority}) must be between 1 and 5.")

        self.id = id
        self.location = location
        self.weight = weight
        self.priority = priority

    def __repr__(self):
        return (f"pkg(id={self.id}, loc={self.location}, "
                f"w={self.weight}, p={self.priority})")


# --- helper functions ---

def calculate_distance(loc1, loc2):
    """calculates euclidean distance between two locations."""
    return math.dist(loc1, loc2)


def calculate_route_distance(route, packages_dict):
    """calculates the total distance for a single vehicle's route."""
    if not route:
        return 0.0
    # Ensure all package IDs in the route exist in the dictionary
    if not all(pkg_id in packages_dict for pkg_id in route):
        # Find the missing ID for a better error message
        missing_ids = [pkg_id for pkg_id in route if pkg_id not in packages_dict]
        print(f"error: package id(s) {missing_ids} not found in packages_dict during distance calculation.")
        return float('inf')  # Return infinite distance for invalid route

    try:
        distance = calculate_distance(SHOP_LOCATION, packages_dict[route[0]].location)  # shop to first
        for i in range(len(route) - 1):
            pkg1_id = route[i]
            pkg2_id = route[i + 1]
            distance += calculate_distance(packages_dict[pkg1_id].location,
                                           packages_dict[pkg2_id].location)
        distance += calculate_distance(packages_dict[route[-1]].location, SHOP_LOCATION)  # last to shop
    except KeyError as e:
        print(f"error: keyerror accessing package location during distance calculation: {e}. route: {route}")
        return float('inf')  # Return infinite distance if a key error occurs
    return distance


def calculate_total_distance(solution, packages_dict):
    """calculates the total distance for all vehicles in a solution."""
    total_dist = 0.0
    if solution is None:  # Handle cases where algorithm returns None
        return float('inf')
    for route in solution:
        dist = calculate_route_distance(route, packages_dict)
        if dist == float('inf'):  # Propagate error state
            return float('inf')
        total_dist += dist
    return total_dist


def get_route_weight(route, packages_dict):
    """calculates the total weight of packages in a route."""
    # Ensure all package IDs in the route exist in the dictionary
    if not all(pkg_id in packages_dict for pkg_id in route):
        missing_ids = [pkg_id for pkg_id in route if pkg_id not in packages_dict]
        print(f"error: package id(s) {missing_ids} not found in packages_dict during weight calculation.")
        # Depending on how this is used, returning 0 or raising error might be appropriate
        # Returning a large value might be safer if used in capacity checks
        return float('inf')
    try:
        return sum(packages_dict[pkg_id].weight for pkg_id in route)
    except KeyError as e:
        print(f"error: keyerror accessing package weight during weight calculation: {e}. route: {route}")
        return float('inf')


# --- MODIFIED: is_valid_solution ---
def is_valid_solution(solution, packages_intended_for_assignment, vehicles_capacity, packages_dict):
    """checks if a solution is valid (capacity constraints & assignment uniqueness)."""
    assigned_package_ids = set()
    if not isinstance(solution, list) or len(solution) != len(vehicles_capacity):
        return False, "incorrect number of routes for vehicles or invalid solution format."

    # Check capacity and duplicate assignments per vehicle
    for i, route in enumerate(solution):
        if not isinstance(route, list):
            return False, f"route {i + 1} is not a list."
        route_weight = 0
        current_route_ids = set()
        for pkg_id in route:
            # Basic type/existence check
            if not isinstance(pkg_id, str):
                return False, f"invalid package id type '{pkg_id}' in route {i + 1}."
            if pkg_id not in packages_dict:
                # Check if it was *intended* to be assignable - might indicate logic error elsewhere
                intended_ids = {p.id for p in packages_intended_for_assignment}
                if pkg_id in intended_ids:
                    return False, f"invalid package id '{pkg_id}' in route {i + 1} - found in intended list but not in master dictionary."
                else:
                    # This case is odd - package in route but not in master dict *or* intended list.
                    return False, f"unknown package id '{pkg_id}' in route {i + 1}."

            # Check for assignment to multiple vehicles
            if pkg_id in assigned_package_ids:
                return False, f"package {pkg_id} assigned to multiple vehicles."
            # Check for duplicates within the *same* route (less likely but possible bug)
            if pkg_id in current_route_ids:
                return False, f"package {pkg_id} appears multiple times in route {i + 1}."

            assigned_package_ids.add(pkg_id)
            current_route_ids.add(pkg_id)
            route_weight += packages_dict[pkg_id].weight

        # Check capacity for the vehicle
        if route_weight > vehicles_capacity[i]:
            return False, f"vehicle {i + 1} exceeds capacity ({route_weight:.2f}kg > {vehicles_capacity[i]}kg)."

    # If we reach here, all capacity and uniqueness checks passed for the assigned packages.
    # We no longer fail the solution if some 'intended' packages are missing,
    # as this might be due to capacity limits being filled by higher-priority items
    # or optimization choices. The reporting function will list unassigned items.
    return True, "solution is valid (capacity and uniqueness)."


# --- MODIFIED: generate_initial_solution ---
def generate_initial_solution(packages, num_vehicles, vehicles_capacity, packages_dict):
    """generates an initial valid solution, prioritizing higher priority packages."""
    # check for packages too heavy for any vehicle
    assignable_packages = []
    unassignable_packages_ids = []  # Store IDs of packages that cannot fit anywhere
    if not vehicles_capacity:  # Handle case with zero vehicles
        unassignable_packages_ids = [pkg.id for pkg in packages]
        print("warning: no vehicles available, all packages are unassignable.")
    else:
        for pkg in packages:
            # Check if it fits in *at least* one vehicle based on its weight
            can_fit_somewhere = any(pkg.weight <= cap for cap in vehicles_capacity)
            if can_fit_somewhere:
                assignable_packages.append(pkg)
            else:
                unassignable_packages_ids.append(pkg.id)  # Mark as unassignable due to weight/capacity mismatch

    if unassignable_packages_ids:
        print(
            f"info: packages {unassignable_packages_ids} are too heavy for any single vehicle and will not be assigned.")

    current_solution = [[] for _ in range(num_vehicles)]
    current_weights = [0] * num_vehicles

    # Sort packages by priority (ascending, 1 is highest) before assignment
    packages_to_assign = sorted(assignable_packages, key=lambda p: p.priority)

    assigned_count = 0
    packages_left_unassigned_ids = []  # Track packages that couldn't be placed

    # Iterate through sorted packages (high priority first)
    for pkg in packages_to_assign:
        assigned = False
        # Try assigning to vehicles (start checking from a random vehicle index for better distribution)
        start_vehicle_idx = random.randrange(num_vehicles) if num_vehicles > 0 else 0
        for i in range(num_vehicles):
            vehicle_idx = (start_vehicle_idx + i) % num_vehicles
            if current_weights[vehicle_idx] + pkg.weight <= vehicles_capacity[vehicle_idx]:
                current_solution[vehicle_idx].append(pkg.id)
                current_weights[vehicle_idx] += pkg.weight
                assigned = True
                assigned_count += 1
                break  # Assigned to this vehicle, move to next package

        if not assigned:
            # This package couldn't fit in *any* vehicle given the current assignments
            packages_left_unassigned_ids.append(pkg.id)

    if packages_left_unassigned_ids:
        # This is expected if capacity is limited
        print(
            f"info: packages left unassigned after initial prioritized assignment (due to capacity limits): {packages_left_unassigned_ids}")

    # randomize order within each route initially (important for exploring different sequences)
    for route in current_solution:
        random.shuffle(route)

    # Validate the initial solution using the simplified validator
    # Pass the original list of packages that *could* have been assigned.
    is_valid, reason = is_valid_solution(current_solution, assignable_packages, vehicles_capacity, packages_dict)
    if not is_valid:
        # This should be less likely now, but indicates a potential bug in the assignment logic above
        print(f"critical warning: initial prioritized solution generation failed validation: {reason}")
        print(f"critical warning: generated solution was: {current_solution}")
        # Returning an empty solution might hide the root cause
        # Let's return the potentially flawed solution for debugging, but maybe algorithms should handle it?
        # For now, return the flawed one with the warning.
        print("warning: proceeding with potentially invalid initial solution.")

    return current_solution


# --- simulated annealing ---

def get_neighbor_solution(current_solution, vehicles_capacity, packages_dict):
    """generates a neighboring solution by making a small random change."""
    neighbor = copy.deepcopy(current_solution)
    num_vehicles = len(neighbor)
    if num_vehicles == 0: return neighbor  # no vehicles, no change

    possible_moves = []
    # 1. move package within the same route
    for r_idx, route in enumerate(neighbor):
        if len(route) >= 2:
            possible_moves.append(("intra_swap", r_idx))
    # 2. move package to another vehicle
    for r1_idx, route1 in enumerate(neighbor):
        if route1:  # if source route is not empty
            for r2_idx in range(num_vehicles):
                if r1_idx != r2_idx:
                    possible_moves.append(("inter_move", r1_idx, r2_idx))
    # 3. swap packages between two different vehicles
    for r1_idx in range(num_vehicles):
        for r2_idx in range(r1_idx + 1, num_vehicles):
            if neighbor[r1_idx] and neighbor[r2_idx]:  # both routes must have packages
                possible_moves.append(("inter_swap", r1_idx, r2_idx))

    if not possible_moves:
        # print("debug: no possible moves found in get_neighbor_solution")
        return neighbor  # cannot make any moves

    # Try multiple attempts to find a *valid* move, as capacity checks might fail often
    max_attempts = 30  # increased attempts
    for attempt in range(max_attempts):
        move_type = random.choice(possible_moves)
        temp_neighbor = copy.deepcopy(neighbor)  # work on a temporary copy for validation
        valid_move_found = False

        try:
            if move_type[0] == "intra_swap":
                r_idx = move_type[1]
                if len(temp_neighbor[r_idx]) < 2: continue
                idx1, idx2 = random.sample(range(len(temp_neighbor[r_idx])), 2)
                temp_neighbor[r_idx][idx1], temp_neighbor[r_idx][idx2] = temp_neighbor[r_idx][idx2], \
                temp_neighbor[r_idx][idx1]
                valid_move_found = True  # This move never violates capacity

            elif move_type[0] == "inter_move":
                r1_idx, r2_idx = move_type[1], move_type[2]
                if not temp_neighbor[r1_idx]: continue  # source route cannot be empty

                pkg_idx_to_move = random.randrange(len(temp_neighbor[r1_idx]))
                pkg_id = temp_neighbor[r1_idx][pkg_idx_to_move]

                # Ensure package exists before getting weight
                if pkg_id not in packages_dict: continue
                pkg_weight = packages_dict[pkg_id].weight

                # check capacity of destination vehicle
                current_weight_r2 = get_route_weight(temp_neighbor[r2_idx], packages_dict)
                if current_weight_r2 == float('inf'): continue  # Skip if error in weight calc

                if current_weight_r2 + pkg_weight <= vehicles_capacity[r2_idx]:
                    moved_pkg = temp_neighbor[r1_idx].pop(pkg_idx_to_move)
                    insert_pos = random.randint(0, len(temp_neighbor[r2_idx]))
                    temp_neighbor[r2_idx].insert(insert_pos, moved_pkg)
                    valid_move_found = True

            elif move_type[0] == "inter_swap":
                r1_idx, r2_idx = move_type[1], move_type[2]
                if not temp_neighbor[r1_idx] or not temp_neighbor[r2_idx]: continue

                idx1 = random.randrange(len(temp_neighbor[r1_idx]))
                idx2 = random.randrange(len(temp_neighbor[r2_idx]))
                pkg1_id = temp_neighbor[r1_idx][idx1]
                pkg2_id = temp_neighbor[r2_idx][idx2]

                # Ensure packages exist
                if pkg1_id not in packages_dict or pkg2_id not in packages_dict: continue
                pkg1_weight = packages_dict[pkg1_id].weight
                pkg2_weight = packages_dict[pkg2_id].weight

                # check capacities after swap
                current_weight_r1 = get_route_weight(temp_neighbor[r1_idx], packages_dict)
                current_weight_r2 = get_route_weight(temp_neighbor[r2_idx], packages_dict)
                if current_weight_r1 == float('inf') or current_weight_r2 == float('inf'): continue

                if (current_weight_r1 - pkg1_weight + pkg2_weight <= vehicles_capacity[r1_idx] and
                        current_weight_r2 - pkg2_weight + pkg1_weight <= vehicles_capacity[r2_idx]):
                    temp_neighbor[r1_idx][idx1], temp_neighbor[r2_idx][idx2] = temp_neighbor[r2_idx][idx2], \
                    temp_neighbor[r1_idx][idx1]
                    valid_move_found = True

        except IndexError:
            continue  # retry if index error occurs
        except KeyError as e:
            print(f"error: keyerror during neighbor generation: {e}")
            continue  # retry

        if valid_move_found:
            neighbor = temp_neighbor  # commit the valid move
            # apply nn refinement occasionally after a successful move
            if random.random() < 0.1 and num_vehicles > 0:
                route_to_optimize_idx = random.randrange(num_vehicles)
                route_to_optimize = neighbor[route_to_optimize_idx]
                if len(route_to_optimize) > 1:
                    optimized_route = nearest_neighbor_route_optimization(route_to_optimize, packages_dict)
                    # check capacity again after reordering
                    opt_weight = get_route_weight(optimized_route, packages_dict)
                    if opt_weight != float('inf') and opt_weight <= vehicles_capacity[route_to_optimize_idx]:
                        neighbor[route_to_optimize_idx] = optimized_route
                    # else: keep original route if nn optimization failed or violated capacity

            return neighbor  # return the valid neighbor

    # if no valid move found after max_attempts, return original solution
    # print("debug: no valid neighbor found after attempts.")
    return neighbor


def nearest_neighbor_route_optimization(package_ids, packages_dict):
    """optimizes the order of packages within a single route using nn."""
    if not package_ids:
        return []

    # Filter out any IDs not present in the dictionary to prevent errors
    valid_package_ids = [pkg_id for pkg_id in package_ids if pkg_id in packages_dict]
    if not valid_package_ids:
        # print("warning: no valid package ids found for nn optimization.")
        return []  # Return empty if no valid packages

    start_node = valid_package_ids[0]
    unvisited = set(valid_package_ids)
    current_node = start_node
    ordered_route = [current_node]
    unvisited.remove(current_node)

    current_location = packages_dict[current_node].location

    while unvisited:
        nearest_neighbor = min(unvisited,
                               key=lambda pkg_id: calculate_distance(current_location, packages_dict[pkg_id].location))
        ordered_route.append(nearest_neighbor)
        unvisited.remove(nearest_neighbor)
        current_node = nearest_neighbor
        current_location = packages_dict[current_node].location

    return ordered_route


def simulated_annealing(packages, num_vehicles, vehicles_capacity, packages_dict,
                        initial_temp, cooling_rate, stopping_temp, iter_per_temp):
    """performs the simulated annealing optimization."""

    # identify initially unassignable packages (too heavy)
    assignable_packages = []
    initially_unassigned_heavy_ids = []
    if not vehicles_capacity:
        initially_unassigned_heavy_ids = [pkg.id for pkg in packages]
    else:
        for pkg in packages:
            can_fit_somewhere = any(pkg.weight <= cap for cap in vehicles_capacity)
            if can_fit_somewhere:
                assignable_packages.append(pkg)
            else:
                initially_unassigned_heavy_ids.append(pkg.id)

    if initially_unassigned_heavy_ids:
        print(f"[sa] packages {initially_unassigned_heavy_ids} too heavy, excluding from optimization.")

    # generate initial solution using the prioritized method
    current_solution = generate_initial_solution(assignable_packages, num_vehicles, vehicles_capacity, packages_dict)
    current_cost = calculate_total_distance(current_solution, packages_dict)

    # Ensure initial cost is not inf before proceeding
    if current_cost == float('inf'):
        print("error: initial solution has infinite cost, cannot start sa.")
        # Returning empty solution might be appropriate here
        return [[] for _ in range(num_vehicles)], float('inf'), 0, initially_unassigned_heavy_ids

    best_solution = copy.deepcopy(current_solution)
    best_cost = current_cost
    temperature = initial_temp

    start_time = time.time()

    while temperature > stopping_temp:
        for _ in range(iter_per_temp):
            neighbor_solution = get_neighbor_solution(current_solution, vehicles_capacity, packages_dict)
            neighbor_cost = calculate_total_distance(neighbor_solution, packages_dict)

            # skip if neighbor calculation resulted in error (inf cost)
            if neighbor_cost == float('inf'):
                # print("debug sa: skipping neighbor with infinite cost.")
                continue

            # check if the neighbor is valid (using simplified validator)
            # pass the original assignable packages list for context if needed, though simplified validator doesn't use it directly
            is_valid, reason = is_valid_solution(neighbor_solution, assignable_packages, vehicles_capacity,
                                                 packages_dict)
            if not is_valid:
                # print(f"debug sa: invalid neighbor generated: {reason}. skipping.")
                continue  # skip invalid neighbors

            cost_diff = neighbor_cost - current_cost

            # acceptance criteria
            if cost_diff < 0 or (temperature > 0 and random.random() < math.exp(-cost_diff / temperature)):
                current_solution = neighbor_solution
                current_cost = neighbor_cost

                # update best solution found so far
                if current_cost < best_cost:
                    best_solution = copy.deepcopy(current_solution)
                    best_cost = current_cost

        temperature *= cooling_rate
        # print(f"temp: {temperature:.2f}, current cost: {current_cost:.2f}, best cost: {best_cost:.2f}")

    end_time = time.time()
    computation_time = end_time - start_time

    # final validation of the best solution found
    if best_solution is not None:
        is_valid, reason = is_valid_solution(best_solution, assignable_packages, vehicles_capacity, packages_dict)
        if not is_valid:
            print(f"error: final sa solution is invalid! reason: {reason}")
            print("warning: returning potentially invalid sa solution.")
    else:
        # handle case where no valid solution was ever found (should be rare now)
        print("warning: sa did not find any valid solution.")
        return [[] for _ in range(num_vehicles)], float('inf'), computation_time, initially_unassigned_heavy_ids

    return best_solution, best_cost, computation_time, initially_unassigned_heavy_ids


# --- genetic algorithm ---

def initialize_population(pop_size, packages, num_vehicles, vehicles_capacity, packages_dict, assignable_packages):
    """creates the initial population for ga."""
    population = []
    for _ in range(pop_size):
        # use the prioritized initial solution generator
        solution = generate_initial_solution(assignable_packages, num_vehicles, vehicles_capacity, packages_dict)
        population.append(solution)
    return population


def calculate_fitness(solution, packages_dict, packages, vehicles_capacity, assignable_packages):
    """calculates fitness (inverse of distance). handles invalid solutions."""
    # use the simplified validator
    is_valid, _ = is_valid_solution(solution, assignable_packages, vehicles_capacity, packages_dict)
    if not is_valid:
        return 0.0  # invalid solutions have zero fitness

    total_distance = calculate_total_distance(solution, packages_dict)

    # handle infinite distance (error during calculation)
    if total_distance == float('inf'):
        return 0.0  # treat as invalid

    if total_distance == 0:
        # check if there are actually assignable packages that require delivery
        # solution might be [[]] which is valid if no packages are assignable
        if not any(solution):  # if all routes are empty
            if not assignable_packages:  # and no packages were assignable
                return float('inf')  # perfect score
            else:  # empty solution but there were packages to assign
                return 0.0  # invalid state
        else:
            # non-empty solution with 0 distance (all packages at depot?)
            return 1e12  # very high fitness if valid and 0 distance

    return 1.0 / total_distance


def tournament_selection(population, fitnesses, k):
    """selects an individual using tournament selection."""
    best_individual_idx = -1  # store index instead of object
    best_fitness = -1.0

    # ensure we don't pick more candidates than population size
    actual_k = min(k, len(population))
    if actual_k <= 0: return None  # handle empty or invalid k

    selected_indices = random.sample(range(len(population)), actual_k)

    for i in selected_indices:
        if fitnesses[i] > best_fitness:
            best_fitness = fitnesses[i]
            best_individual_idx = i

    # handle case where all selected had 0 fitness (e.g., all invalid)
    if best_individual_idx == -1 and population:
        # return a random individual's index as fallback
        return random.randrange(len(population))

    return best_individual_idx  # return index


def crossover(parent1, parent2, num_vehicles, packages_dict, vehicles_capacity, assignable_packages):
    """performs crossover between two parents to create offspring."""
    # route-based crossover: pick a random vehicle, offspring1 gets p1's route,
    # offspring2 gets p2's route. then distribute remaining packages.

    offspring1 = [[] for _ in range(num_vehicles)]
    offspring2 = [[] for _ in range(num_vehicles)]
    offspring1_weights = [0] * num_vehicles
    offspring2_weights = [0] * num_vehicles
    assigned_to_offspring1 = set()
    assigned_to_offspring2 = set()

    all_package_ids = {pkg.id for pkg in assignable_packages}

    # choose a crossover point (which vehicle's route to swap)
    crossover_vehicle = -1  # default if no vehicles
    if num_vehicles > 0:
        crossover_vehicle = random.randrange(num_vehicles)

        # inherit the chosen route directly (if valid and exists)
        # check parent lengths for safety
        if crossover_vehicle < len(parent1) and parent1[crossover_vehicle]:
            route1 = parent1[crossover_vehicle]
            w1 = get_route_weight(route1, packages_dict)
            # check capacity and weight calculation success
            if w1 != float('inf') and w1 <= vehicles_capacity[crossover_vehicle]:
                offspring1[crossover_vehicle] = route1[:]
                offspring1_weights[crossover_vehicle] = w1
                assigned_to_offspring1.update(route1)

        if crossover_vehicle < len(parent2) and parent2[crossover_vehicle]:
            route2 = parent2[crossover_vehicle]
            w2 = get_route_weight(route2, packages_dict)
            if w2 != float('inf') and w2 <= vehicles_capacity[crossover_vehicle]:
                offspring2[crossover_vehicle] = route2[:]
                offspring2_weights[crossover_vehicle] = w2
                assigned_to_offspring2.update(route2)

    # distribute remaining packages (those not in the inherited routes)
    # sort remaining by priority to give them a better chance?
    remaining_packages_for_o1 = sorted(
        [pkg for pkg in assignable_packages if pkg.id not in assigned_to_offspring1],
        key=lambda p: p.priority
    )
    remaining_packages_for_o2 = sorted(
        [pkg for pkg in assignable_packages if pkg.id not in assigned_to_offspring2],
        key=lambda p: p.priority
    )
    # random.shuffle(remaining_packages_for_o1) # keep priority sort
    # random.shuffle(remaining_packages_for_o2)

    # assign remaining to offspring 1
    for pkg in remaining_packages_for_o1:
        assigned = False
        start_idx = random.randrange(num_vehicles) if num_vehicles > 0 else 0
        for i in range(num_vehicles):
            v_idx = (start_idx + i) % num_vehicles
            # allow adding to the inherited route if capacity permits
            if offspring1_weights[v_idx] + pkg.weight <= vehicles_capacity[v_idx]:
                offspring1[v_idx].append(pkg.id)
                offspring1_weights[v_idx] += pkg.weight
                assigned = True
                break
        # if not assigned: print(f"warning crossover o1: could not assign remaining pkg {pkg.id}")

    # assign remaining to offspring 2
    for pkg in remaining_packages_for_o2:
        assigned = False
        start_idx = random.randrange(num_vehicles) if num_vehicles > 0 else 0
        for i in range(num_vehicles):
            v_idx = (start_idx + i) % num_vehicles
            if offspring2_weights[v_idx] + pkg.weight <= vehicles_capacity[v_idx]:
                offspring2[v_idx].append(pkg.id)
                offspring2_weights[v_idx] += pkg.weight
                assigned = True
                break
        # if not assigned: print(f"warning crossover o2: could not assign remaining pkg {pkg.id}")

    # randomize order within newly added parts of routes (or all?)
    for v_idx in range(num_vehicles):
        # shuffle all routes - simpler and might explore better
        random.shuffle(offspring1[v_idx])
        random.shuffle(offspring2[v_idx])

    return offspring1, offspring2


def mutate(solution, mutation_rate, vehicles_capacity, packages_dict, assignable_packages):
    """applies mutation to a solution."""
    mutated_solution = copy.deepcopy(solution)
    num_vehicles = len(mutated_solution)
    if num_vehicles == 0: return mutated_solution

    # mutation: use similar operations as sa neighbor generation
    # attempt mutation multiple times? or increase probability?
    # let's try applying *each* type of mutation with the given probability

    # 1. inter-route move
    if random.random() < mutation_rate:
        if num_vehicles > 1:  # need at least two vehicles to move between
            # choose non-empty source and different destination
            non_empty_routes_idx = [i for i, r in enumerate(mutated_solution) if r]
            if len(non_empty_routes_idx) > 0:
                r1_idx = random.choice(non_empty_routes_idx)
                possible_dest = [i for i in range(num_vehicles) if i != r1_idx]
                if possible_dest:
                    r2_idx = random.choice(possible_dest)

                    # proceed with move if source route still has packages
                    if mutated_solution[r1_idx]:
                        pkg_idx_to_move = random.randrange(len(mutated_solution[r1_idx]))
                        pkg_id = mutated_solution[r1_idx][pkg_idx_to_move]

                        if pkg_id in packages_dict:  # check existence
                            pkg_weight = packages_dict[pkg_id].weight
                            current_weight_r2 = get_route_weight(mutated_solution[r2_idx], packages_dict)

                            if current_weight_r2 != float('inf') and current_weight_r2 + pkg_weight <= \
                                    vehicles_capacity[r2_idx]:
                                moved_pkg = mutated_solution[r1_idx].pop(pkg_idx_to_move)
                                insert_pos = random.randint(0, len(mutated_solution[r2_idx]))
                                mutated_solution[r2_idx].insert(insert_pos, moved_pkg)
                                # print(f"debug mutate: moved {pkg_id} from {r1_idx} to {r2_idx}")

    # 2. intra-route swap
    if random.random() < mutation_rate:
        if num_vehicles > 0:
            # choose a route with at least 2 packages
            swappable_routes_idx = [i for i, r in enumerate(mutated_solution) if len(r) >= 2]
            if swappable_routes_idx:
                r_idx = random.choice(swappable_routes_idx)
                idx1, idx2 = random.sample(range(len(mutated_solution[r_idx])), 2)
                mutated_solution[r_idx][idx1], mutated_solution[r_idx][idx2] = mutated_solution[r_idx][idx2], \
                mutated_solution[r_idx][idx1]
                # print(f"debug mutate: swapped within route {r_idx}")

    # 3. inter-route swap (less frequent?)
    if random.random() < mutation_rate * 0.5:  # lower chance for inter-swap
        if num_vehicles > 1:
            # choose two distinct non-empty routes
            non_empty_routes_idx = [i for i, r in enumerate(mutated_solution) if r]
            if len(non_empty_routes_idx) >= 2:
                r1_idx, r2_idx = random.sample(non_empty_routes_idx, 2)

                # select packages to swap
                idx1 = random.randrange(len(mutated_solution[r1_idx]))
                idx2 = random.randrange(len(mutated_solution[r2_idx]))
                pkg1_id = mutated_solution[r1_idx][idx1]
                pkg2_id = mutated_solution[r2_idx][idx2]

                if pkg1_id in packages_dict and pkg2_id in packages_dict:  # check existence
                    pkg1_weight = packages_dict[pkg1_id].weight
                    pkg2_weight = packages_dict[pkg2_id].weight

                    # check capacities after swap
                    current_weight_r1 = get_route_weight(mutated_solution[r1_idx], packages_dict)
                    current_weight_r2 = get_route_weight(mutated_solution[r2_idx], packages_dict)

                    if current_weight_r1 != float('inf') and current_weight_r2 != float('inf'):
                        if (current_weight_r1 - pkg1_weight + pkg2_weight <= vehicles_capacity[r1_idx] and
                                current_weight_r2 - pkg2_weight + pkg1_weight <= vehicles_capacity[r2_idx]):
                            # perform swap
                            mutated_solution[r1_idx][idx1], mutated_solution[r2_idx][idx2] = mutated_solution[r2_idx][
                                idx2], mutated_solution[r1_idx][idx1]
                            # print(f"debug mutate: swapped between routes {r1_idx} and {r2_idx}")

    # 4. optional: nn refinement
    if random.random() < 0.05 and num_vehicles > 0:  # lower chance
        refinable_routes_idx = [i for i, r in enumerate(mutated_solution) if len(r) > 1]
        if refinable_routes_idx:
            route_to_optimize_idx = random.choice(refinable_routes_idx)
            route_to_optimize = mutated_solution[route_to_optimize_idx]
            optimized_route = nearest_neighbor_route_optimization(route_to_optimize, packages_dict)
            opt_weight = get_route_weight(optimized_route, packages_dict)
            # apply only if valid and capacity respected
            if opt_weight != float('inf') and opt_weight <= vehicles_capacity[route_to_optimize_idx]:
                mutated_solution[route_to_optimize_idx] = optimized_route

    return mutated_solution


def genetic_algorithm(packages, num_vehicles, vehicles_capacity, packages_dict,
                      pop_size, mutation_rate, num_generations, tournament_size):
    """performs the genetic algorithm optimization."""

    # identify initially unassignable packages (too heavy)
    assignable_packages = []
    initially_unassigned_heavy_ids = []
    if not vehicles_capacity:
        initially_unassigned_heavy_ids = [pkg.id for pkg in packages]
    else:
        for pkg in packages:
            can_fit_somewhere = any(pkg.weight <= cap for cap in vehicles_capacity)
            if can_fit_somewhere:
                assignable_packages.append(pkg)
            else:
                initially_unassigned_heavy_ids.append(pkg.id)

    if initially_unassigned_heavy_ids:
        print(f"[ga] packages {initially_unassigned_heavy_ids} too heavy, excluding from optimization.")

    start_time = time.time()

    # initialize population using prioritized generator
    population = initialize_population(pop_size, packages, num_vehicles, vehicles_capacity, packages_dict,
                                       assignable_packages)
    best_solution_overall = None
    best_fitness_overall = -1.0

    # find initial best
    fitnesses_init = [calculate_fitness(ind, packages_dict, packages, vehicles_capacity, assignable_packages) for ind in
                      population]
    valid_fitnesses_init = [f for f in fitnesses_init if f > 0]  # consider only valid solutions

    if valid_fitnesses_init:
        best_fitness_overall = max(valid_fitnesses_init)
        # find the first index corresponding to the best fitness
        best_idx_init = -1
        for idx, fit in enumerate(fitnesses_init):
            if fit == best_fitness_overall:
                best_idx_init = idx
                break
        if best_idx_init != -1:
            best_solution_overall = copy.deepcopy(population[best_idx_init])
        else:
            print("warning: could not find index for initial best fitness.")
    else:
        print("warning: no valid solutions found in initial ga population.")
        # start with an empty best solution if none are valid initially
        best_solution_overall = [[] for _ in range(num_vehicles)]
        best_fitness_overall = 0.0  # or calculate fitness for empty solution

    for generation in range(num_generations):
        # calculate fitness for the current population
        fitnesses = [calculate_fitness(ind, packages_dict, packages, vehicles_capacity, assignable_packages) for ind in
                     population]

        # find best in current generation among valid solutions
        current_best_fitness = 0.0
        current_best_idx = -1
        valid_indices = [i for i, f in enumerate(fitnesses) if f > 0]
        if valid_indices:
            current_best_fitness = max(fitnesses[i] for i in valid_indices)
            # find the first index with this fitness
            for i in valid_indices:
                if fitnesses[i] == current_best_fitness:
                    current_best_idx = i
                    break

        # update overall best if current generation's best is better
        if current_best_idx != -1 and current_best_fitness > best_fitness_overall:
            best_fitness_overall = current_best_fitness
            best_solution_overall = copy.deepcopy(population[current_best_idx])
            # print(f"gen {generation}: new best fitness: {best_fitness_overall:.6f} (distance: {1/best_fitness_overall if best_fitness_overall > 0 else float('inf'):.2f})")

        # create next generation
        new_population = []

        # elitism: keep the best individual found so far
        if best_solution_overall is not None:  # ensure we have a valid best one
            # verify the elite member is still valid before adding
            is_elite_valid, _ = is_valid_solution(best_solution_overall, assignable_packages, vehicles_capacity,
                                                  packages_dict)
            if is_elite_valid:
                new_population.append(copy.deepcopy(best_solution_overall))
            else:
                print(f"warning: elite solution became invalid in gen {generation}, not adding.")

        # fill the rest of the population using selection, crossover, mutation
        while len(new_population) < pop_size:
            # selection - get indices of parents
            parent1_idx = tournament_selection(population, fitnesses, tournament_size)
            parent2_idx = tournament_selection(population, fitnesses, tournament_size)

            # ensure valid indices were returned
            if parent1_idx is None or parent2_idx is None or parent1_idx >= len(population) or parent2_idx >= len(
                    population):
                # fallback: add a random valid individual if possible, or regenerate
                # print(f"debug: selection failed (p1:{parent1_idx}, p2:{parent2_idx}), adding random.")
                valid_pop_indices = [i for i, f in enumerate(fitnesses) if f > 0]
                if valid_pop_indices:
                    new_population.append(copy.deepcopy(population[random.choice(valid_pop_indices)]))
                else:  # if no valid individuals exist, regenerate one
                    new_population.append(
                        generate_initial_solution(assignable_packages, num_vehicles, vehicles_capacity, packages_dict))

                if len(new_population) >= pop_size: break  # stop if full
                continue  # try selection again

            parent1 = population[parent1_idx]
            parent2 = population[parent2_idx]

            # crossover
            offspring1, offspring2 = crossover(parent1, parent2, num_vehicles, packages_dict, vehicles_capacity,
                                               assignable_packages)

            # mutation
            mutated_offspring1 = mutate(offspring1, mutation_rate, vehicles_capacity, packages_dict,
                                        assignable_packages)
            mutated_offspring2 = mutate(offspring2, mutation_rate, vehicles_capacity, packages_dict,
                                        assignable_packages)

            # add to new population (ensure not exceeding pop_size)
            if len(new_population) < pop_size:
                new_population.append(mutated_offspring1)
            if len(new_population) < pop_size:
                new_population.append(mutated_offspring2)

        population = new_population

        # optional: print progress
        # if generation % 50 == 0 or generation == num_generations - 1:
        #      dist = 1/best_fitness_overall if best_fitness_overall > 0 else float('inf')
        #      print(f"generation {generation+1}/{num_generations}. best distance so far: {dist:.2f}")

    end_time = time.time()
    computation_time = end_time - start_time

    # calculate final best cost from best fitness
    best_cost = 1.0 / best_fitness_overall if best_fitness_overall > 0 else float('inf')

    # final validation of the best solution found
    if best_solution_overall:
        is_valid, reason = is_valid_solution(best_solution_overall, assignable_packages, vehicles_capacity,
                                             packages_dict)
        if not is_valid:
            print(f"error: final ga solution is invalid! reason: {reason}")
            print("warning: returning potentially invalid ga solution.")
            # maybe return the last known valid best solution? or empty?
            # for now, return the potentially invalid one
    else:
        # handle case where no valid solution was ever found
        print("warning: ga did not find any valid solution.")
        return [[] for _ in range(num_vehicles)], float('inf'), computation_time, initially_unassigned_heavy_ids

    return best_solution_overall, best_cost, computation_time, initially_unassigned_heavy_ids


# --- user interface (tkinter) ---

class DeliveryApp:
    def __init__(self, master):
        self.master = master
        master.title("package delivery optimizer")
        master.geometry("850x750")  # slightly wider for new button

        self.packages = []
        self.packages_dict = {}
        self.vehicles_capacity = []
        self.last_run_assignable_packages = []  # Store assignable packages from last run for reporting

        # style
        style = ttk.Style()
        style.theme_use('clam')  # more modern theme

        # main frame
        main_frame = ttk.Frame(master, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # input frame
        input_frame = ttk.LabelFrame(main_frame, text="input parameters", padding="10")
        input_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        input_frame.columnconfigure(4, weight=1)  # allow expansion for buttons

        # vehicles
        ttk.Label(input_frame, text="number of vehicles:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.num_vehicles_var = tk.StringVar(value="1")  # Default to 1 for user's test case
        self.num_vehicles_entry = ttk.Entry(input_frame, textvariable=self.num_vehicles_var, width=5)
        self.num_vehicles_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(input_frame, text="capacity per vehicle (kg):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.vehicle_capacity_var = tk.StringVar(value="100")  # Default to 100 for user's test case
        self.vehicle_capacity_entry = ttk.Entry(input_frame, textvariable=self.vehicle_capacity_var, width=7)
        self.vehicle_capacity_entry.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)

        # packages frame
        package_ctrl_frame = ttk.Frame(input_frame)
        package_ctrl_frame.grid(row=1, column=0, columnspan=5, padx=5, pady=5, sticky=tk.W)

        ttk.Label(package_ctrl_frame, text="packages:").pack(side=tk.LEFT, padx=(0, 10))

        self.generate_button = ttk.Button(package_ctrl_frame, text="generate random",
                                          command=self.generate_random_packages)
        self.generate_button.pack(side=tk.LEFT, padx=5)

        self.manual_entry_button = ttk.Button(package_ctrl_frame, text="manual entry",
                                              command=self.open_manual_entry_popup)
        self.manual_entry_button.pack(side=tk.LEFT, padx=5)

        # label for random package count (optional, but can be useful)
        ttk.Label(package_ctrl_frame, text="random count:").pack(side=tk.LEFT, padx=(15, 5))
        self.num_packages_var = tk.StringVar(value="3")  # Default to 3 for user's test case
        self.num_packages_entry = ttk.Entry(package_ctrl_frame, textvariable=self.num_packages_var, width=5)
        self.num_packages_entry.pack(side=tk.LEFT)

        # algorithm selection
        algo_frame = ttk.LabelFrame(main_frame, text="algorithm settings", padding="10")
        algo_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        self.algo_var = tk.StringVar(value="SA")
        ttk.Radiobutton(algo_frame, text="simulated annealing (sa)", variable=self.algo_var, value="SA",
                        command=self.update_parameter_display).grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        ttk.Radiobutton(algo_frame, text="genetic algorithm (ga)", variable=self.algo_var, value="GA",
                        command=self.update_parameter_display).grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)

        # sa parameters frame
        self.sa_frame = ttk.Frame(algo_frame, padding="5")
        self.sa_frame.grid(row=0, column=1, padx=10, sticky=(tk.W, tk.N))
        ttk.Label(self.sa_frame, text="cooling rate (0.90-0.99):").grid(row=0, column=0, sticky=tk.W)
        self.sa_cooling_rate_var = tk.StringVar(value=str(SA_COOLING_RATE_DEFAULT))
        self.sa_cooling_rate_entry = ttk.Entry(self.sa_frame, textvariable=self.sa_cooling_rate_var, width=6)
        self.sa_cooling_rate_entry.grid(row=0, column=1, padx=5)
        # fixed sa params displayed as labels
        ttk.Label(self.sa_frame, text=f"initial temp: {SA_INITIAL_TEMP}").grid(row=1, column=0, sticky=tk.W,
                                                                               columnspan=2)
        ttk.Label(self.sa_frame, text=f"stopping temp: {SA_STOPPING_TEMP}").grid(row=2, column=0, sticky=tk.W,
                                                                                 columnspan=2)
        ttk.Label(self.sa_frame, text=f"iterations/temp: {SA_ITERATIONS_PER_TEMP}").grid(row=3, column=0, sticky=tk.W,
                                                                                         columnspan=2)

        # ga parameters frame
        self.ga_frame = ttk.Frame(algo_frame, padding="5")
        self.ga_frame.grid(row=1, column=1, padx=10, sticky=(tk.W, tk.N))
        ttk.Label(self.ga_frame, text="population size (50-100):").grid(row=0, column=0, sticky=tk.W)
        self.ga_pop_size_var = tk.StringVar(value=str(GA_POPULATION_SIZE_DEFAULT))
        self.ga_pop_size_entry = ttk.Entry(self.ga_frame, textvariable=self.ga_pop_size_var, width=6)
        self.ga_pop_size_entry.grid(row=0, column=1, padx=5)
        ttk.Label(self.ga_frame, text="mutation rate (0.01-0.1):").grid(row=1, column=0, sticky=tk.W)
        self.ga_mutation_rate_var = tk.StringVar(value=str(GA_MUTATION_RATE_DEFAULT))
        self.ga_mutation_rate_entry = ttk.Entry(self.ga_frame, textvariable=self.ga_mutation_rate_var, width=6)
        self.ga_mutation_rate_entry.grid(row=1, column=1, padx=5)
        # fixed ga params displayed as labels
        ttk.Label(self.ga_frame, text=f"generations: {GA_NUM_GENERATIONS}").grid(row=2, column=0, sticky=tk.W,
                                                                                 columnspan=2)
        ttk.Label(self.ga_frame, text=f"tournament size: {GA_TOURNAMENT_SIZE}").grid(row=3, column=0, sticky=tk.W,
                                                                                     columnspan=2)

        self.update_parameter_display()  # initialize visibility

        # run button
        self.run_button = ttk.Button(main_frame, text="run optimization", command=self.run_optimization)
        self.run_button.pack(side=tk.TOP, pady=10)

        # output frame
        output_frame = ttk.LabelFrame(main_frame, text="output / package list", padding="10")
        output_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=5)

        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, height=15, width=80)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.output_text.configure(state='disabled')  # read-only initially

        # initialize with some default packages matching user's test case
        self.initialize_test_case_packages()
        self.display_packages()

    def initialize_test_case_packages(self):
        """sets up the specific test case packages provided by the user."""
        self.packages = []
        self.packages_dict = {}
        test_data = [
            {"id": "P1", "loc": (64.65, 7.46), "w": 50.0, "p": 1},
            {"id": "P2", "loc": (77.51, 8.69), "w": 50.0, "p": 2},
            {"id": "P3", "loc": (19.12, 81.79), "w": 50.0, "p": 3},
        ]
        for data in test_data:
            try:
                pkg = Package(data["id"], data["loc"], data["w"], data["p"])
                self.packages.append(pkg)
                self.packages_dict[pkg.id] = pkg
            except ValueError as e:
                messagebox.showerror("package error", f"error creating test package {data['id']}: {e}",
                                     parent=self.master)
        print("initialized with test case packages.")

    def update_parameter_display(self):
        """show/hide parameter entry based on selected algorithm."""
        algo = self.algo_var.get()
        if algo == "SA":
            self.sa_frame.grid(row=0, column=1, padx=10, sticky=(tk.W, tk.N))
            self.ga_frame.grid_remove()
        elif algo == "GA":
            self.ga_frame.grid(row=1, column=1, padx=10, sticky=(tk.W, tk.N))
            self.sa_frame.grid_remove()

    def display_packages(self):
        """displays the current list of packages in the output area."""
        output_str = "current packages:\n"
        output_str += "id | location (x, y) | weight (kg) | priority (1-5)\n"
        output_str += "---|-----------------|-------------|-----------------\n"

        if not self.packages:
            output_str += "(no packages defined)\n"
        else:
            # sort by id for consistent display (handle potential non-numeric ids)
            def get_sort_key(p):
                try:
                    return int(p.id[1:])  # try converting P<number> to int
                except:
                    return p.id  # fallback to string sort if format differs

            try:
                sorted_packages = sorted(self.packages, key=get_sort_key)
            except Exception as e:
                print(f"warning: error sorting packages by id ({e}), using original order.")
                sorted_packages = self.packages

            for package in sorted_packages:
                output_str += (
                    f"{package.id:<3} | ({package.location[0]:<6.2f}, {package.location[1]:<6.2f}) | "  # format floats
                    f"{package.weight:<11.1f} | {package.priority}\n")

        self.output_text.configure(state='normal')
        self.output_text.delete('1.0', tk.END)
        self.output_text.insert(tk.END, output_str)
        self.output_text.configure(state='disabled')
        # print(f"displayed {len(self.packages)} packages.")

    def generate_random_packages(self):
        """generates random packages based on input number."""
        try:
            num_packages = int(self.num_packages_var.get())
            if num_packages <= 0:
                raise ValueError("number of packages must be positive.")
        except ValueError as e:
            messagebox.showerror("input error", f"invalid number of packages: {e}", parent=self.master)
            return

        self.packages = []
        self.packages_dict = {}

        for i in range(num_packages):
            pkg_id = f"P{i + 1}"
            location = (round(random.uniform(X_RANGE[0], X_RANGE[1]), 2),
                        round(random.uniform(Y_RANGE[0], Y_RANGE[1]), 2))
            # ensure weight allows for some packing, avoid too many tiny/huge ones
            weight = max(1.0, round(random.gauss(mu=20, sigma=15), 1))  # mean 20kg, std dev 15kg, min 1kg
            priority = random.randint(1, 5)
            try:
                package = Package(pkg_id, location, weight, priority)
                self.packages.append(package)
                self.packages_dict[pkg_id] = package
            except ValueError as e:
                messagebox.showerror("package error", f"error generating package {pkg_id}: {e}", parent=self.master)
                # skip this package if invalid params somehow generated
                continue

        print(f"generated {len(self.packages)} random packages.")
        self.display_packages()  # update the text area

    def open_manual_entry_popup(self):
        """opens a popup window for manual package entry."""
        popup = Toplevel(self.master)
        popup.title("manual package entry")
        popup.geometry("450x400")
        popup.transient(self.master)  # keep popup on top of main window
        popup.grab_set()  # disable main window interaction

        ttk.Label(popup, text="enter package details below (one per line):").pack(pady=(10, 0))
        ttk.Label(popup, text="format: x, y, weight, priority").pack()
        ttk.Label(popup, text=f"(e.g., 25.5, 70.2, 15, 2)").pack(pady=(0, 10))

        text_area = Text(popup, height=15, width=50, wrap=tk.WORD)
        text_area.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        # prefill with current packages if any exist
        current_data = ""
        if self.packages:
            # sort by id for consistent display (handle potential non-numeric ids)
            def get_sort_key(p):
                try:
                    return int(p.id[1:])  # try converting P<number> to int
                except:
                    return p.id  # fallback to string sort if format differs

            try:
                sorted_packages = sorted(self.packages, key=get_sort_key)
            except Exception as e:
                print(f"warning: error sorting packages by id ({e}), using original order.")
                sorted_packages = self.packages

            for pkg in sorted_packages:
                current_data += f"{pkg.location[0]}, {pkg.location[1]}, {pkg.weight}, {pkg.priority}\n"
        text_area.insert("1.0", current_data)

        button_frame = ttk.Frame(popup)
        button_frame.pack(pady=10)

        def submit_manual_packages():
            raw_text = text_area.get("1.0", tk.END).strip()
            lines = raw_text.split('\n')
            new_packages = []
            new_packages_dict = {}
            errors = []

            for i, line in enumerate(lines):
                line = line.strip()
                if not line or line.startswith('#'):  # ignore empty lines and comments
                    continue

                parts = [p.strip() for p in line.split(',')]
                if len(parts) != 4:
                    errors.append(
                        f"line {i + 1}: invalid format - expected 4 values (x, y, weight, priority), got {len(parts)}.")
                    continue

                try:
                    x = float(parts[0])
                    y = float(parts[1])
                    weight = float(parts[2])
                    priority = int(parts[3])
                    pkg_id = f"P{len(new_packages) + 1}"  # generate id sequentially

                    # create package object (performs validation)
                    package = Package(pkg_id, (x, y), weight, priority)
                    new_packages.append(package)
                    new_packages_dict[pkg_id] = package

                except ValueError as e:
                    errors.append(f"line {i + 1}: invalid value - {e}")
                except Exception as e:
                    errors.append(f"line {i + 1}: unexpected error - {e}")

            if errors:
                messagebox.showerror("input errors", "please fix the following errors:\n\n" + "\n".join(errors),
                                     parent=popup)
            else:
                # update main application's package list
                self.packages = new_packages
                self.packages_dict = new_packages_dict
                print(f"manually entered {len(self.packages)} packages.")
                self.display_packages()  # update the main text area
                popup.destroy()  # close popup on success

        submit_button = ttk.Button(button_frame, text="submit", command=submit_manual_packages)
        submit_button.pack(side=tk.LEFT, padx=10)

        cancel_button = ttk.Button(button_frame, text="cancel", command=popup.destroy)
        cancel_button.pack(side=tk.LEFT, padx=10)

        # wait for the popup to close before returning
        self.master.wait_window(popup)

    def run_optimization(self):
        """gets parameters, runs the selected algorithm, and displays results."""
        # --- get and validate inputs ---
        try:
            num_vehicles = int(self.num_vehicles_var.get())
            vehicle_capacity = float(self.vehicle_capacity_var.get())
            if num_vehicles <= 0 or vehicle_capacity <= 0:
                raise ValueError("number of vehicles and capacity must be positive.")
            self.vehicles_capacity = [vehicle_capacity] * num_vehicles  # assume uniform capacity

            algo = self.algo_var.get()

            # sa params
            sa_cooling_rate = float(self.sa_cooling_rate_var.get())
            if not (0.90 <= sa_cooling_rate <= 0.99):
                raise ValueError("sa cooling rate must be between 0.90 and 0.99.")

            # ga params
            ga_pop_size = int(self.ga_pop_size_var.get())
            if not (50 <= ga_pop_size <= 100):
                raise ValueError("ga population size must be between 50 and 100.")
            ga_mutation_rate = float(self.ga_mutation_rate_var.get())
            if not (0.01 <= ga_mutation_rate <= 0.1):
                raise ValueError("ga mutation rate must be between 0.01 and 0.1.")

        except ValueError as e:
            messagebox.showerror("input error", f"invalid input parameter: {e}", parent=self.master)
            return

        if not self.packages:
            messagebox.showwarning("no packages",
                                   "please generate or manually enter packages before running optimization.",
                                   parent=self.master)
            return

        # --- run selected algorithm ---
        solution = None
        cost = float('inf')
        computation_time = 0
        unassigned_heavy_packages_ids = []  # Store IDs only

        # make copies to pass to algorithms, so they don't modify the main list/dict directly
        current_packages = copy.deepcopy(self.packages)
        current_packages_dict = copy.deepcopy(self.packages_dict)

        # Determine which packages are assignable *before* running the algorithm
        # This list is needed for reporting unassigned packages correctly
        self.last_run_assignable_packages = []
        temp_unassigned_heavy = []
        if not self.vehicles_capacity:
            temp_unassigned_heavy = [pkg.id for pkg in current_packages]
        else:
            for pkg in current_packages:
                if any(pkg.weight <= cap for cap in self.vehicles_capacity):
                    self.last_run_assignable_packages.append(pkg)
                else:
                    temp_unassigned_heavy.append(pkg.id)
        unassigned_heavy_packages_ids = temp_unassigned_heavy

        try:
            if algo == "SA":
                print("running simulated annealing...")
                # Pass only the packages list, SA will determine assignable internally now
                solution, cost, computation_time, _ = simulated_annealing(
                    current_packages, num_vehicles, self.vehicles_capacity, current_packages_dict,
                    SA_INITIAL_TEMP, sa_cooling_rate, SA_STOPPING_TEMP, SA_ITERATIONS_PER_TEMP
                )
                # The list of heavy packages is determined outside now
            elif algo == "GA":
                print("running genetic algorithm...")
                # Pass only the packages list, GA will determine assignable internally now
                solution, cost, computation_time, _ = genetic_algorithm(
                    current_packages, num_vehicles, self.vehicles_capacity, current_packages_dict,
                    ga_pop_size, ga_mutation_rate, GA_NUM_GENERATIONS, GA_TOURNAMENT_SIZE
                )
                # The list of heavy packages is determined outside now
            else:
                messagebox.showerror("error", "invalid algorithm selected.", parent=self.master)
                return

        except Exception as e:
            messagebox.showerror("runtime error", f"an error occurred during optimization: {e}", parent=self.master)
            import traceback
            traceback.print_exc()  # print full traceback to console for debugging
            return

        # --- display results ---
        # use the original self.packages_dict for displaying details
        self.display_results(solution, cost, computation_time, algo, unassigned_heavy_packages_ids, self.packages_dict)

    def display_results(self, solution, cost, computation_time, algo_name, unassigned_heavy_packages_ids,
                        display_packages_dict):
        """formats and displays the optimization results in the text area."""
        # start by displaying the current package list again for reference
        self.display_packages()

        # append the optimization results
        output_str = f"\n\n--- optimization results ({algo_name}) ---\n\n"
        output_str += f"computation time: {computation_time:.4f} seconds\n"
        output_str += f"total distance: {cost:.2f} km\n\n"

        if unassigned_heavy_packages_ids:
            output_str += f"unassigned packages (too heavy): {', '.join(sorted(unassigned_heavy_packages_ids))}\n\n"

        total_assigned_weight = 0
        total_assigned_packages_count = 0
        all_assigned_in_solution_ids = set()

        if solution is None:
            output_str += "no solution found.\n"
        elif not any(solution):  # check if all routes are empty
            output_str += "no packages were assigned by the algorithm.\n"
            # Check if there were actually packages that *should* have been assignable
            if self.last_run_assignable_packages:
                output_str += "(there were assignable packages available - check algorithm logic/parameters).\n"
            else:
                output_str += "(no assignable packages were available).\n"
        else:
            output_str += "vehicle assignments & routes:\n"
            output_str += "-----------------------------\n"
            for i, route in enumerate(solution):
                # use the display_packages_dict passed in for details
                route_weight = get_route_weight(route, display_packages_dict)
                # handle potential error from get_route_weight
                if route_weight == float('inf'):
                    output_str += f"vehicle {i + 1}: error calculating weight for route {route}\n\n"
                    continue  # skip this route display

                route_distance = calculate_route_distance(route, display_packages_dict)
                if route_distance == float('inf'):
                    output_str += f"vehicle {i + 1}: error calculating distance for route {route}\n\n"
                    continue  # skip this route display

                total_assigned_weight += route_weight
                total_assigned_packages_count += len(route)
                all_assigned_in_solution_ids.update(route)

                output_str += f"vehicle {i + 1} (capacity: {self.vehicles_capacity[i]} kg):\n"
                output_str += f"  - weight loaded: {route_weight:.2f} kg\n"
                output_str += f"  - route distance: {route_distance:.2f} km\n"
                output_str += f"  - route order: shop -> "
                if route:
                    route_details = []
                    for pkg_id in route:
                        # check if package exists in the display dictionary
                        if pkg_id in display_packages_dict:
                            pkg = display_packages_dict[pkg_id]
                            route_details.append(f"{pkg.id} (w:{pkg.weight:.1f}, p:{pkg.priority})")  # format weight
                        else:
                            route_details.append(f"{pkg_id} (details missing!)")  # indicate if data is missing
                    output_str += " -> ".join(route_details)
                    output_str += " -> shop\n\n"
                else:
                    output_str += " (no packages assigned)\n\n"

            output_str += f"\n--- summary ---\n"
            output_str += f"total packages assigned in solution: {total_assigned_packages_count}\n"

            # calculate assignable packages based on the *original* list used for the run
            assignable_ids = {pkg.id for pkg in self.last_run_assignable_packages}
            output_str += f"total packages available (assignable): {len(assignable_ids)}\n"

            # check for packages that were assignable but not included in the final solution
            unassigned_but_should_be = assignable_ids - all_assigned_in_solution_ids
            if unassigned_but_should_be:
                output_str += f"packages not assigned by algorithm (due to capacity/optimization): {', '.join(sorted(list(unassigned_but_should_be)))}\n"

            output_str += f"total weight assigned: {total_assigned_weight:.2f} kg\n"
            output_str += f"total distance across all vehicles: {cost:.2f} km\n"

        self.output_text.configure(state='normal')
        # append results instead of clearing
        self.output_text.insert(tk.END, output_str)
        self.output_text.yview(tk.END)  # scroll to bottom
        self.output_text.configure(state='disabled')
        print(f"displayed results for {algo_name}.")


# --- main execution ---

if __name__ == "__main__":
    root = tk.Tk()
    app = DeliveryApp(root)
    root.mainloop()
