from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class CoordinatePoint(BaseModel):
    """A single coordinate point with optional metadata"""
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")
    name: Optional[str] = Field(None, description="Optional location name")
    service_time_minutes: int = Field(5, ge=0, le=120, description="Time to spend at this location")
    load_kg: float = Field(0.0, ge=0.0, description="Load weight in kg")


class CoordinateOptimizationRequest(BaseModel):
    """Request for coordinate-based route optimization"""
    start: CoordinatePoint = Field(..., description="Starting point (depot)")
    end: Optional[CoordinatePoint] = Field(None, description="Ending point (if different from start)")
    waypoints: List[CoordinatePoint] = Field(..., min_items=1, description="Delivery/stop locations")
    use_traffic: bool = Field(True, description="Use real-time traffic data")
    optimize_order: bool = Field(True, description="Optimize the order of waypoints")
    max_vehicles: int = Field(1, ge=1, le=10, description="Number of vehicles available")
    vehicle_capacity_kg: float = Field(500.0, ge=1.0, description="Vehicle capacity in kg")
    departure_time: Optional[datetime] = Field(None, description="Planned departure time")


class RouteSegment(BaseModel):
    """A segment of the route between two points"""
    from_location: CoordinatePoint
    to_location: CoordinatePoint
    distance_km: float
    duration_minutes: int
    traffic_delay_minutes: int = 0
    congestion_level: str = "LOW"


class CoordinateOptimizationResponse(BaseModel):
    """Response for coordinate-based route optimization"""
    success: bool
    total_distance_km: float
    total_duration_minutes: int
    total_traffic_delay_minutes: int
    optimized_sequence: List[int]  # Indices showing optimized waypoint order
    route_segments: List[RouteSegment]
    waypoints_in_order: List[CoordinatePoint]  # Waypoints in optimized order
    summary: dict
