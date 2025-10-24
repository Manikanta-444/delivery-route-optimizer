"""
Coordinate-based route optimizer
Optimizes routes using direct coordinates without requiring database orders
"""
from typing import List, Dict
import logging
from app.services.traffic_client import TrafficClient
from app.schemas.coordinate_optimization import (
    CoordinatePoint, CoordinateOptimizationRequest, 
    CoordinateOptimizationResponse, RouteSegment
)
from app.schemas.optimization import LocationPoint, OptimizationConstraints
from app.services.vrp_solver import VRPSolver

logger = logging.getLogger(__name__)


class CoordinateOptimizer:
    """Optimize routes based on raw coordinates"""
    
    def __init__(self):
        self.traffic_client = TrafficClient()
        self.vrp_solver = VRPSolver()
    
    def optimize_route(self, request: CoordinateOptimizationRequest) -> CoordinateOptimizationResponse:
        """
        Optimize route for given coordinates
        
        Args:
            request: Coordinate optimization request
            
        Returns:
            Optimized route with segments and timing
        """
        try:
            # Convert coordinates to LocationPoint objects
            locations = self._convert_to_location_points(request)
            
            # Create constraints for VRP solver
            constraints = OptimizationConstraints(
                max_vehicles=request.max_vehicles,
                vehicle_capacity_kg=request.vehicle_capacity_kg,
                optimization_criteria="MINIMIZE_TIME" if request.use_traffic else "MINIMIZE_DISTANCE"
            )
            
            # Solve VRP if optimization is requested
            if request.optimize_order and len(request.waypoints) > 1:
                solution = self.vrp_solver.solve_vrp(locations, constraints, request.use_traffic)
                
                if not solution.get("success"):
                    raise Exception(solution.get("error", "Optimization failed"))
                
                # Extract optimized route
                return self._build_response_from_vrp(solution, request, locations)
            else:
                # Simple sequential route without optimization
                return self._build_sequential_route(request, locations)
                
        except Exception as e:
            logger.error(f"Coordinate optimization error: {e}")
            raise
    
    def _convert_to_location_points(self, request: CoordinateOptimizationRequest) -> List[LocationPoint]:
        """Convert coordinate points to LocationPoint objects for VRP solver"""
        locations = []
        
        # Add start point as depot
        locations.append(LocationPoint(
            order_id=None,
            latitude=request.start.lat,
            longitude=request.start.lng,
            service_time_minutes=0,
            load_kg=0
        ))
        
        # Add all waypoints
        for wp in request.waypoints:
            locations.append(LocationPoint(
                order_id=None,
                latitude=wp.lat,
                longitude=wp.lng,
                service_time_minutes=wp.service_time_minutes,
                load_kg=wp.load_kg
            ))
        
        return locations
    
    def _build_response_from_vrp(
        self, 
        solution: Dict, 
        request: CoordinateOptimizationRequest,
        locations: List[LocationPoint]
    ) -> CoordinateOptimizationResponse:
        """Build response from VRP solver solution"""
        
        # Get the first route (assuming single vehicle for coordinate optimization)
        route = solution["routes"][0] if solution["routes"] else None
        
        if not route:
            raise Exception("No route generated")
        
        # Extract waypoint sequence
        stops = route["stops"]
        optimized_sequence = []
        waypoints_in_order = []
        route_segments = []
        
        total_traffic_delay = 0
        
        for i, stop in enumerate(stops):
            if i == 0:  # Skip depot
                continue
            
            # Map stop back to original waypoint index (subtract 1 for depot)
            waypoint_idx = stop["stop_sequence"] - 1
            if waypoint_idx >= 0 and waypoint_idx < len(request.waypoints):
                optimized_sequence.append(waypoint_idx)
                waypoints_in_order.append(request.waypoints[waypoint_idx])
            
            # Create route segment
            if i > 0:
                from_stop = stops[i-1]
                to_stop = stop
                
                # Get traffic data for this segment
                traffic_data = self.traffic_client.get_traffic_flow(
                    from_stop["latitude"], 
                    from_stop["longitude"]
                )
                
                congestion_level = traffic_data.get("congestion_level", "LOW")
                travel_time = stop.get("travel_time_from_previous", 0)
                
                # Estimate traffic delay based on congestion
                traffic_delay = self._estimate_traffic_delay(travel_time, congestion_level)
                total_traffic_delay += traffic_delay
                
                segment = RouteSegment(
                    from_location=CoordinatePoint(
                        lat=from_stop["latitude"],
                        lng=from_stop["longitude"]
                    ),
                    to_location=CoordinatePoint(
                        lat=to_stop["latitude"],
                        lng=to_stop["longitude"]
                    ),
                    distance_km=stop.get("distance_from_previous", 0),
                    duration_minutes=travel_time,
                    traffic_delay_minutes=traffic_delay,
                    congestion_level=congestion_level
                )
                route_segments.append(segment)
        
        return CoordinateOptimizationResponse(
            success=True,
            total_distance_km=route["total_distance_km"],
            total_duration_minutes=route["total_distance_minutes"],
            total_traffic_delay_minutes=total_traffic_delay,
            optimized_sequence=optimized_sequence,
            route_segments=route_segments,
            waypoints_in_order=waypoints_in_order,
            summary={
                "vehicles_used": 1,
                "total_stops": len(waypoints_in_order),
                "optimization_applied": True,
                "traffic_aware": request.use_traffic
            }
        )
    
    def _build_sequential_route(
        self,
        request: CoordinateOptimizationRequest,
        locations: List[LocationPoint]
    ) -> CoordinateOptimizationResponse:
        """Build simple sequential route without optimization"""
        
        route_segments = []
        total_distance = 0
        total_duration = 0
        total_traffic_delay = 0
        
        # Create segments between consecutive points
        all_points = [request.start] + request.waypoints
        
        for i in range(len(all_points) - 1):
            from_point = all_points[i]
            to_point = all_points[i + 1]
            
            # Calculate travel time with traffic
            travel_time = self.traffic_client.calculate_travel_time(
                from_point.lat, from_point.lng,
                to_point.lat, to_point.lng
            )
            
            # Get traffic data
            traffic_data = self.traffic_client.get_traffic_flow(
                from_point.lat, from_point.lng
            )
            
            congestion_level = traffic_data.get("congestion_level", "LOW")
            distance = self.traffic_client._calculate_distance(
                from_point.lat, from_point.lng,
                to_point.lat, to_point.lng
            )
            
            traffic_delay = self._estimate_traffic_delay(travel_time, congestion_level)
            
            segment = RouteSegment(
                from_location=from_point,
                to_location=to_point,
                distance_km=distance,
                duration_minutes=travel_time,
                traffic_delay_minutes=traffic_delay,
                congestion_level=congestion_level
            )
            
            route_segments.append(segment)
            total_distance += distance
            total_duration += travel_time
            total_traffic_delay += traffic_delay
        
        return CoordinateOptimizationResponse(
            success=True,
            total_distance_km=round(total_distance, 2),
            total_duration_minutes=total_duration,
            total_traffic_delay_minutes=total_traffic_delay,
            optimized_sequence=list(range(len(request.waypoints))),  # Sequential order
            route_segments=route_segments,
            waypoints_in_order=request.waypoints,
            summary={
                "vehicles_used": 1,
                "total_stops": len(request.waypoints),
                "optimization_applied": False,
                "traffic_aware": request.use_traffic
            }
        )
    
    @staticmethod
    def _estimate_traffic_delay(travel_time: int, congestion_level: str) -> int:
        """Estimate traffic delay based on congestion level"""
        delay_factors = {
            "LOW": 0.0,
            "MODERATE": 0.2,
            "HIGH": 0.5,
            "SEVERE": 1.0
        }
        factor = delay_factors.get(congestion_level, 0.0)
        return int(travel_time * factor)
