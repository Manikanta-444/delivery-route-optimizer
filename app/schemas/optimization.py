from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
import uuid


class OptimizationConstraints(BaseModel):
    max_stops_per_route: int = Field(10, ge=1, le=50)
    max_route_duration_minutes: int = Field(480, ge=60, le=720)  # 1-12 hours
    max_vehicles: int = Field(1, ge=1, le=10)
    vehicle_capacity_kg: Decimal = Field(Decimal("500.0"), ge=Decimal("1.0"))
    optimization_criteria: str = Field(
        "MINIMIZE_DISTANCE",
        pattern="^(MINIMIZE_DISTANCE|MINIMIZE_TIME|MINIMIZE_COST)$"
    )
    depot_latitude: Optional[float] = None
    depot_longitude: Optional[float] = None
    working_hours_start: str = Field("08:00", pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    working_hours_end: str = Field("18:00", pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$")


class OptimizationRequest(BaseModel):
    order_ids: List[uuid.UUID] = Field(..., min_items=1, max_items=100)
    constraints: OptimizationConstraints = OptimizationConstraints()
    job_name: Optional[str] = None
    use_traffic_data: bool = True


class LocationPoint(BaseModel):
    order_id: Optional[uuid.UUID] = None
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    service_time_minutes: int = Field(10, ge=0, le=120)
    load_kg: Decimal = Field(Decimal("0.0"), ge=Decimal("0.0"))
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None


class RouteStopResponse(BaseModel):
    stop_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    stop_sequence: int
    stop_type: str
    address_latitude: Decimal
    address_longitude: Decimal
    estimated_arrival_time: Optional[datetime]
    estimated_service_time_minutes: int
    distance_from_previous_km: Optional[Decimal]
    travel_time_from_previous_minutes: Optional[int]
    traffic_delay_minutes: int
    load_pickup_kg: Decimal
    load_delivery_kg: Decimal

    class Config:
        from_attributes = True


class OptimizedRouteResponse(BaseModel):
    route_id: uuid.UUID
    vehicle_id: int
    route_sequence: int
    total_distance_km: Optional[Decimal]
    estimated_duration_minutes: Optional[int]
    estimated_fuel_cost: Optional[Decimal]
    total_load_kg: Optional[Decimal]
    route_status: str
    stops: List[RouteStopResponse] = []

    class Config:
        from_attributes = True


class OptimizationJobResponse(BaseModel):
    job_id: uuid.UUID
    job_name: Optional[str]
    job_status: str
    algorithm_used: str
    total_orders: Optional[int]
    total_distance_km: Optional[Decimal]
    total_estimated_time_minutes: Optional[int]
    optimization_criteria: str
    max_vehicles: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]
    computation_time_seconds: Optional[int]
    error_message: Optional[str]
    routes: List[OptimizedRouteResponse] = []

    class Config:
        from_attributes = True


class OptimizationSummary(BaseModel):
    total_jobs: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int
    avg_computation_time_seconds: Optional[float]
    total_routes_optimized: int
