from sqlalchemy import Column, String, DateTime, Integer, Numeric, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from app.database import Base


class OptimizationJob(Base):
    __tablename__ = 'optimization_jobs'
    __table_args__ = {'schema': 'delivery_route_optimizer'}

    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name = Column(String(255))
    job_status = Column(String(50), default='PENDING')  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    algorithm_used = Column(String(100), default='OR_TOOLS_VRP')
    total_orders = Column(Integer)
    total_distance_km = Column(Numeric(10, 2))
    total_estimated_time_minutes = Column(Integer)
    optimization_criteria = Column(String(50), default='MINIMIZE_DISTANCE')
    max_vehicles = Column(Integer, default=1)
    vehicle_capacity_kg = Column(Numeric(8, 2))
    depot_latitude = Column(Numeric(10, 8))
    depot_longitude = Column(Numeric(11, 8))
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    computation_time_seconds = Column(Integer)
    error_message = Column(Text)

    # Relationships
    routes = relationship("OptimizedRoute", back_populates="job", cascade="all, delete-orphan")


class OptimizedRoute(Base):
    __tablename__ = 'optimized_routes'
    __table_args__ = {'schema': 'delivery_route_optimizer'}

    route_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey('delivery_route_optimizer.optimization_jobs.job_id'), nullable=False)
    vehicle_id = Column(Integer)  # Vehicle number in the optimization
    driver_id = Column(UUID(as_uuid=True))  # Reference to order_service.drivers
    route_sequence = Column(Integer)
    total_distance_km = Column(Numeric(10, 2))
    estimated_duration_minutes = Column(Integer)
    estimated_fuel_cost = Column(Numeric(8, 2))
    total_load_kg = Column(Numeric(8, 2))
    start_time = Column(DateTime)
    estimated_end_time = Column(DateTime)
    route_status = Column(String(50), default='PLANNED')
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("OptimizationJob", back_populates="routes")
    stops = relationship("RouteStop", back_populates="route", cascade="all, delete-orphan")


class RouteStop(Base):
    __tablename__ = 'route_stops'
    __table_args__ = {'schema': 'delivery_route_optimizer'}

    stop_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id = Column(UUID(as_uuid=True), ForeignKey('delivery_route_optimizer.optimized_routes.route_id'), nullable=False)
    order_id = Column(UUID(as_uuid=True))  # Reference to order_service.delivery_orders
    stop_sequence = Column(Integer)
    stop_type = Column(String(20), default='DELIVERY')  # DEPOT, PICKUP, DELIVERY
    address_latitude = Column(Numeric(10, 8), nullable=False)
    address_longitude = Column(Numeric(11, 8), nullable=False)
    estimated_arrival_time = Column(DateTime)
    actual_arrival_time = Column(DateTime)
    estimated_service_time_minutes = Column(Integer, default=10)
    distance_from_previous_km = Column(Numeric(8, 2))
    travel_time_from_previous_minutes = Column(Integer)
    traffic_delay_minutes = Column(Integer, default=0)
    stop_status = Column(String(50), default='PENDING')
    load_pickup_kg = Column(Numeric(8, 2), default=0)
    load_delivery_kg = Column(Numeric(8, 2), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    route = relationship("OptimizedRoute", back_populates="stops")


class RoutePerformanceMetric(Base):
    __tablename__ = 'route_performance_metrics'
    __table_args__ = {'schema': 'delivery_route_optimizer'}

    metric_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id = Column(UUID(as_uuid=True), ForeignKey('delivery_route_optimizer.optimized_routes.route_id'), nullable=False)
    planned_distance_km = Column(Numeric(10, 2))
    actual_distance_km = Column(Numeric(10, 2))
    planned_duration_minutes = Column(Integer)
    actual_duration_minutes = Column(Integer)
    fuel_consumption_liters = Column(Numeric(8, 2))
    carbon_emissions_kg = Column(Numeric(8, 2))
    on_time_deliveries = Column(Integer, default=0)
    late_deliveries = Column(Integer, default=0)
    efficiency_score = Column(Numeric(5, 2))
    created_at = Column(DateTime, default=datetime.utcnow)
