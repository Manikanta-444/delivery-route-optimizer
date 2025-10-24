from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import numpy as np
from typing import List, Dict, Tuple, Optional
from app.services.traffic_client import TrafficClient
from app.schemas.optimization import LocationPoint, OptimizationConstraints
import logging

logger = logging.getLogger(__name__)


class VRPSolver:
    def __init__(self):
        self.traffic_client = TrafficClient()

    def solve_vrp(self, locations: List[LocationPoint], constraints: OptimizationConstraints,
                  use_traffic: bool = True) -> Dict:
        """
        Solve Vehicle Routing Problem with traffic-aware travel times

        Args:
            locations: List of LocationPoint objects (including depot)
            constraints: OptimizationConstraints object
            use_traffic: Whether to use real traffic data

        Returns:
            Dict with optimized routes or error message
        """
        if len(locations) < 2:
            return {"error": "Need at least 2 locations (depot + delivery)"}

        try:
            # Create distance/time matrix
            matrix = self._create_distance_matrix(locations, use_traffic)

            # Create routing model
            manager = pywrapcp.RoutingIndexManager(
                len(locations),
                constraints.max_vehicles,
                0  # depot index
            )
            routing = pywrapcp.RoutingModel(manager)

            # Create distance callback
            def distance_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)
                return int(matrix[from_node][to_node])

            transit_callback_index = routing.RegisterTransitCallback(distance_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

            # Add distance constraint
            if constraints.optimization_criteria == "MINIMIZE_DISTANCE":
                max_distance = constraints.max_route_duration_minutes * 60  # Convert to seconds
            else:
                max_distance = constraints.max_route_duration_minutes * 100  # Time units

            routing.AddDimension(
                transit_callback_index,
                30 * 60,  # 30 minute slack
                max_distance,  # maximum distance per vehicle
                True,  # start cumul to zero
                'Distance'
            )

            # Add capacity constraint if loads are specified
            loads = [float(loc.load_kg) for loc in locations]
            if any(load > 0 for load in loads):
                def demand_callback(from_index):
                    from_node = manager.IndexToNode(from_index)
                    return int(loads[from_node] * 100)  # Convert to grams

                demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
                routing.AddDimensionWithVehicleCapacity(
                    demand_callback_index,
                    0,  # null capacity slack
                    [int(float(constraints.vehicle_capacity_kg) * 100)] * constraints.max_vehicles,
                    True,  # start cumul to zero
                    'Capacity'
                )

            # Set search parameters
            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            )
            search_parameters.local_search_metaheuristic = (
                routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
            )
            search_parameters.time_limit.FromSeconds(30)

            # Solve
            solution = routing.SolveWithParameters(search_parameters)

            if solution:
                return self._extract_solution(manager, routing, solution, locations, matrix)
            else:
                return {"error": "No solution found for the given constraints"}

        except Exception as e:
            logger.error(f"VRP solving error: {e}")
            return {"error": f"Optimization failed: {str(e)}"}

    def _create_distance_matrix(self, locations: List[LocationPoint], use_traffic: bool) -> List[List[int]]:
        """Create distance/time matrix using traffic data or euclidean distance"""
        num_locations = len(locations)
        matrix = [[0 for _ in range(num_locations)] for _ in range(num_locations)]

        for i in range(num_locations):
            for j in range(num_locations):
                if i == j:
                    matrix[i][j] = 0
                else:
                    if use_traffic:
                        travel_time = self.traffic_client.calculate_travel_time(
                            locations[i].latitude, locations[i].longitude,
                            locations[j].latitude, locations[j].longitude
                        )
                        matrix[i][j] = travel_time * 60  # Convert to seconds
                    else:
                        # Use euclidean distance as fallback
                        distance = self._euclidean_distance(
                            locations[i].latitude, locations[i].longitude,
                            locations[j].latitude, locations[j].longitude
                        )
                        # Assume 50 km/h average speed
                        travel_time = int((distance / 50) * 3600)  # seconds
                        matrix[i][j] = max(60, travel_time)  # Minimum 1 minute

        return matrix

    def _euclidean_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate euclidean distance between two points (simplified)"""
        # This is a simplified distance - in real scenarios use Haversine
        lat_diff = lat1 - lat2
        lng_diff = lng1 - lng2
        return ((lat_diff ** 2 + lng_diff ** 2) ** 0.5) * 111  # Rough km conversion

    def _extract_solution(self, manager, routing, solution, locations: List[LocationPoint],
                          matrix: List[List[int]]) -> Dict:
        """Extract the solution from OR-Tools solver"""
        routes = []
        total_distance = 0
        total_time = 0

        for vehicle_id in range(manager.GetNumberOfVehicles()):
            route = []
            index = routing.Start(vehicle_id)
            route_distance = 0
            route_time = 0
            route_load = 0
            previous_index = None

            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                location = locations[node_index]

                # Calculate distance from previous stop
                if route and previous_index is not None:
                    prev_index = manager.IndexToNode(previous_index)
                    travel_time = matrix[prev_index][node_index] // 60  # Convert back to minutes
                    distance = travel_time * 0.8  # Rough distance estimate
                else:
                    travel_time = 0
                    distance = 0

                stop_data = {
                    "stop_sequence": len(route),
                    "order_id": str(location.order_id) if location.order_id else None,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "service_time_minutes": location.service_time_minutes,
                    "load_kg": float(location.load_kg),
                    "travel_time_from_previous": travel_time,
                    "distance_from_previous": distance,
                    "stop_type": "DEPOT" if len(route) == 0 else "DELIVERY"
                }

                route.append(stop_data)
                route_load += float(location.load_kg)

                previous_index = index
                index = solution.Value(routing.NextVar(index))
                if not routing.IsEnd(index):
                    route_distance += routing.GetArcCostForVehicle(previous_index, index, vehicle_id)

            # Only add route if it has stops beyond depot
            if len(route) > 1:
                route_time = route_distance // 60  # Convert to minutes
                routes.append({
                    "vehicle_id": vehicle_id,
                    "route_sequence": vehicle_id,
                    "total_distance_minutes": route_time,
                    "total_distance_km": route_time * 0.8,  # Rough estimate
                    "total_load_kg": route_load,
                    "stops": route
                })
                total_distance += route_time * 0.8
                total_time += route_time

        return {
            "success": True,
            "routes": routes,
            "summary": {
                "total_distance_km": total_distance,
                "total_time_minutes": total_time,
                "vehicles_used": len(routes),
                "total_stops": sum(len(r["stops"]) for r in routes)
            }
        }
