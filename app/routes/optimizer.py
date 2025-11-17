import os
import traceback

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timedelta

from app.database import get_db
from app.models.optimization import OptimizationJob, OptimizedRoute, RouteStop
from app.schemas.optimization import (
    OptimizationRequest, OptimizationJobResponse, OptimizationSummary,
    LocationPoint, OptimizationConstraints
)
from app.schemas.coordinate_optimization import (
    CoordinateOptimizationRequest, CoordinateOptimizationResponse
)
from app.services.vrp_solver import VRPSolver
from app.services.order_client import OrderClient
from app.services.traffic_client import TrafficClient
from app.services.coordinate_optimizer import CoordinateOptimizer
from app.utils.logger import logger, log_exception

router = APIRouter(prefix="/routes", tags=["route-optimization"])

order_client = OrderClient()
traffic_client = TrafficClient()
coordinate_optimizer = CoordinateOptimizer()


@router.post("/optimize", response_model=dict)
async def optimize_routes(
        request: OptimizationRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    """Start route optimization job"""
    try:
        logger.info(f"🚀 New optimization request - {len(request.order_ids)} orders, vehicles={request.constraints.max_vehicles}")
        
        # Validate constraints
        if len(request.order_ids) > 100:
            logger.warning(f"⚠️ Validation failed: {len(request.order_ids)} orders exceeds max of 100")
            raise HTTPException(status_code=400, detail="Maximum 100 orders per optimization")

        # Create optimization job
        job = OptimizationJob(
            job_name=request.job_name or f"Optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            job_status="PENDING",
            total_orders=len(request.order_ids),
            optimization_criteria=request.constraints.optimization_criteria,
            max_vehicles=request.constraints.max_vehicles,
            vehicle_capacity_kg=request.constraints.vehicle_capacity_kg,
            depot_latitude=request.constraints.depot_latitude or float(os.getenv("DEFAULT_DEPOT_LAT", 28.6139)),
            depot_longitude=request.constraints.depot_longitude or float(os.getenv("DEFAULT_DEPOT_LNG", 77.2090))
        )

        db.add(job)
        db.commit()
        db.refresh(job)
        
        logger.info(f"✅ Optimization job created: {job.job_id}")

        # Add to background task
        background_tasks.add_task(
            process_optimization,
            str(job.job_id),
            [str(oid) for oid in request.order_ids],
            request.constraints.dict(),
            request.use_traffic_data,
            db
        )
        
        logger.info(f"🔄 Background task queued for job {job.job_id}")

        return {
            "job_id": job.job_id,
            "status": "PENDING",
            "message": "Optimization job started",
            "estimated_completion_time": datetime.now() + timedelta(minutes=2)
        }
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, "❌ Error creating optimization job", e)
        raise HTTPException(status_code=500, detail=f"Failed to create optimization job: {str(e)}")


@router.post("/optimize-coordinates", response_model=CoordinateOptimizationResponse)
async def optimize_from_coordinates(request: CoordinateOptimizationRequest):
    """
    Optimize route directly from coordinates without requiring database orders.
    
    This endpoint allows direct route optimization by providing start, end, and waypoint coordinates.
    It uses real-time traffic data and VRP algorithms to find the optimal route.
    
    Perfect for:
    - Ad-hoc route planning
    - Testing route scenarios
    - External integrations
    - Quick route calculations
    """
    try:
        logger.info(f"📍 Coordinate optimization request: {len(request.waypoints)} waypoints, traffic={request.use_traffic}, optimize={request.optimize_order}")
        
        result = coordinate_optimizer.optimize_route(request)
        
        logger.info(f"✅ Optimization successful: {result.total_distance_km}km, {result.total_duration_minutes}min, traffic_delay={result.total_traffic_delay_minutes}min")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, "❌ Coordinate optimization failed", e)
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")


@router.get("/jobs/{job_id}", response_model=OptimizationJobResponse)
def get_optimization_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get optimization job status and results"""
    try:
        logger.info(f"🔍 Fetching job: {job_id}")
        
        job = db.query(OptimizationJob).filter(OptimizationJob.job_id == job_id).first()
        if not job:
            logger.warning(f"⚠️ Job not found: {job_id}")
            raise HTTPException(status_code=404, detail="Job not found")
        
        logger.info(f"✅ Job found: {job_id}, status={job.job_status}")
        return job
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, f"❌ Error fetching job {job_id}", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch job: {str(e)}")


@router.get("/jobs", response_model=List[OptimizationJobResponse])
def get_all_jobs(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
        status: Optional[str] = Query(None, regex="^(PENDING|IN_PROGRESS|COMPLETED|FAILED)$"),
        db: Session = Depends(get_db)
):
    """Get all optimization jobs with optional filtering"""
    query = db.query(OptimizationJob)

    if status:
        query = query.filter(OptimizationJob.job_status == status)

    jobs = query.order_by(OptimizationJob.created_at.desc()).offset(skip).limit(limit).all()
    return jobs


@router.get("/summary", response_model=OptimizationSummary)
def get_optimization_summary(db: Session = Depends(get_db)):
    """Get optimization jobs summary statistics"""
    try:
        logger.info("📊 Generating optimization summary")
        
        total_jobs = db.query(OptimizationJob).count()
        pending_jobs = db.query(OptimizationJob).filter(OptimizationJob.job_status == "PENDING").count()
        completed_jobs = db.query(OptimizationJob).filter(OptimizationJob.job_status == "COMPLETED").count()
        failed_jobs = db.query(OptimizationJob).filter(OptimizationJob.job_status == "FAILED").count()

        # Calculate average computation time for completed jobs
        completed_job_times = db.query(OptimizationJob.computation_time_seconds).filter(
            OptimizationJob.job_status == "COMPLETED",
            OptimizationJob.computation_time_seconds.isnot(None)
        ).all()

        avg_computation_time = None
        if completed_job_times:
            avg_computation_time = sum(t[0] for t in completed_job_times) / len(completed_job_times)

        # Count total routes
        total_routes = db.query(OptimizedRoute).count()
        
        logger.info(f"✅ Summary generated: {total_jobs} jobs, {completed_jobs} completed, {failed_jobs} failed")

        return OptimizationSummary(
            total_jobs=total_jobs,
            pending_jobs=pending_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            avg_computation_time_seconds=avg_computation_time,
            total_routes_optimized=total_routes
        )
    except Exception as e:
        log_exception(logger, "❌ Error generating summary", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")


@router.delete("/jobs/{job_id}")
def delete_optimization_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete optimization job and all related data"""
    try:
        logger.info(f"🗑️ Deleting job: {job_id}")
        
        job = db.query(OptimizationJob).filter(OptimizationJob.job_id == job_id).first()
        if not job:
            logger.warning(f"⚠️ Job not found for deletion: {job_id}")
            raise HTTPException(status_code=404, detail="Job not found")

        db.delete(job)
        db.commit()
        
        logger.info(f"✅ Job deleted successfully: {job_id}")
        return {"message": "Job deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, f"❌ Error deleting job {job_id}", e)
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")


async def process_optimization(job_id: str, order_ids: List[str], constraints: dict,
                               use_traffic: bool, db: Session):
    """Background task to process optimization"""
    try:
        # Get job from database
        job = db.query(OptimizationJob).filter(OptimizationJob.job_id == uuid.UUID(job_id)).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # Update job status
        job.job_status = "IN_PROGRESS"
        db.commit()

        start_time = datetime.now()

        # Convert order_ids back to UUIDs
        order_uuids = [uuid.UUID(oid) for oid in order_ids]

        # Create location points (including depot)
        locations = []

        # Add depot as first location
        depot_lat = job.depot_latitude
        depot_lng = job.depot_longitude
        locations.append(LocationPoint(
            order_id=None,
            latitude=float(depot_lat),
            longitude=float(depot_lng),
            service_time_minutes=0,
            load_kg=0
        ))

        # Add order locations (mock data for now)
        # In real implementation, fetch from order service
        for i, order_id in enumerate(order_uuids):
            # Mock coordinates around Delhi
            base_lat = 28.6139
            base_lng = 77.2090

            locations.append(LocationPoint(
                order_id=order_id,
                latitude=base_lat + (i * 0.01),  # Spread orders around
                longitude=base_lng + (i * 0.01),
                service_time_minutes=10,
                load_kg=5.0  # Mock 5kg per order
            ))

        # Convert constraints dict back to object
        constraints_obj = OptimizationConstraints(**constraints)

        # Solve VRP
        solver = VRPSolver()
        solution = solver.solve_vrp(locations, constraints_obj, use_traffic)

        if solution.get("success"):
            # Save routes to database
            total_distance = 0
            total_time = 0

            for route_data in solution["routes"]:
                route = OptimizedRoute(
                    job_id=uuid.UUID(job_id),
                    vehicle_id=route_data["vehicle_id"],
                    route_sequence=route_data["route_sequence"],
                    total_distance_km=route_data["total_distance_km"],
                    estimated_duration_minutes=route_data["total_distance_minutes"],
                    total_load_kg=route_data["total_load_kg"]
                )
                db.add(route)
                db.flush()

                # Save stops
                for stop_data in route_data["stops"]:
                    stop = RouteStop(
                        route_id=route.route_id,
                        order_id=uuid.UUID(stop_data["order_id"]) if stop_data["order_id"] else None,
                        stop_sequence=stop_data["stop_sequence"],
                        stop_type=stop_data["stop_type"],
                        address_latitude=stop_data["latitude"],
                        address_longitude=stop_data["longitude"],
                        estimated_service_time_minutes=stop_data["service_time_minutes"],
                        distance_from_previous_km=stop_data.get("distance_from_previous", 0),
                        travel_time_from_previous_minutes=stop_data.get("travel_time_from_previous", 0),
                        load_delivery_kg=stop_data["load_kg"]
                    )
                    db.add(stop)

                total_distance += route_data["total_distance_km"]
                total_time += route_data["total_distance_minutes"]

            # Update job as completed
            job.job_status = "COMPLETED"
            job.total_distance_km = total_distance
            job.total_estimated_time_minutes = total_time

        else:
            job.job_status = "FAILED"
            job.error_message = solution.get("error", "Unknown optimization error")

        job.completed_at = datetime.now()
        job.computation_time_seconds = (job.completed_at - start_time).seconds
        db.commit()

        logger.info(f"Optimization job {job_id} completed with status: {job.job_status}")

    except Exception as e:
        # Handle errors
        logger.error(f"Optimization job {job_id} failed: {e}")
        logger.error(f"{str(e)}: Traceback: {traceback.format_exc()}")
        job = db.query(OptimizationJob).filter(OptimizationJob.job_id == uuid.UUID(job_id)).first()
        if job:
            job.job_status = "FAILED"
            job.error_message = str(e)
            job.completed_at = datetime.now()
            db.commit()

@router.get("/order/{order_id}")
def get_route_by_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Get the optimized route for a specific order.
    
    Returns the route that contains this order, along with all stops in sequence.
    """
    try:
        logger.info(f"📦 Looking up route for order: {order_id}")
        
        # Find the stop that contains this order
        stop = db.query(RouteStop).filter(RouteStop.order_id == order_id).first()
        
        if not stop:
            logger.warning(f"⚠️ No route found for order: {order_id}")
            raise HTTPException(status_code=404, detail=f"No route found for order {order_id}")
        
        # Get the route this stop belongs to
        route = db.query(OptimizedRoute).filter(OptimizedRoute.route_id == stop.route_id).first()
        
        if not route:
            logger.error(f"❌ Route data missing for stop: {stop.stop_id}")
            raise HTTPException(status_code=404, detail="Route not found")
        
        # Get all stops in this route
        all_stops = db.query(RouteStop).filter(
            RouteStop.route_id == route.route_id
        ).order_by(RouteStop.stop_sequence).all()
        
        # Get the optimization job details
        job = db.query(OptimizationJob).filter(OptimizationJob.job_id == route.job_id).first()
        
        logger.info(f"✅ Route found for order {order_id}: {route.route_id}, {len(all_stops)} stops")
        
        return {
            "order_id": str(order_id),
            "route_id": str(route.route_id),
            "job_id": str(route.job_id),
            "job_name": job.job_name if job else None,
            "vehicle_id": route.vehicle_id,
            "total_distance_km": route.total_distance_km,
            "total_duration_minutes": getattr(route, "estimated_duration_minutes", None),
            "total_stops": len(all_stops),
            "order_stop_sequence": stop.stop_sequence,  # Position of this order in route
            "estimated_arrival_at_order": getattr(stop, "estimated_arrival_time", None),
            "route_status": getattr(route, "route_status", "PENDING"),
            "created_at": route.created_at.isoformat() if route.created_at else None,
            "all_stops": [
                {
                    "stop_id": str(s.stop_id),
                    "order_id": str(s.order_id) if s.order_id else None,
                    "stop_sequence": s.stop_sequence,
                    "stop_type": s.stop_type,
                    "latitude": float(s.address_latitude),
                    "longitude": float(s.address_longitude),
                    "is_current_order": s.order_id == order_id,  # Highlight the requested order
                    "distance_from_previous_km": float(s.distance_from_previous_km) if s.distance_from_previous_km else 0,
                    "travel_time_from_previous_minutes": s.travel_time_from_previous_minutes or 0,
                    "service_time_minutes": s.estimated_service_time_minutes
                }
                for s in all_stops
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        log_exception(logger, f"❌ Error fetching route for order {order_id}", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch route: {str(e)}")


@router.get("")
def get_optimized_routes(db: Session = Depends(get_db)):
    """Get all optimized routes with stops in nested format"""
    try:
        logger.info("🗺️ Fetching all optimized routes")
        
        routes = db.query(OptimizedRoute).all()
        result = []
        for route in routes:
            stops = db.query(RouteStop).filter(RouteStop.route_id == route.route_id).order_by(RouteStop.stop_sequence).all()
            route_dict = {
                "route_id": str(route.route_id),
                "job_id": str(route.job_id),
                "vehicle_id": route.vehicle_id,
                "driver_id": getattr(route, "driver_id", None),
                "route_name": getattr(route, "route_name", None),
                "total_distance_km": route.total_distance_km,
                "total_duration_minutes": getattr(route, "estimated_duration_minutes", None),
                "total_stops": len(stops) - 1,
                "total_weight_kg": getattr(route, "total_load_kg", None),
                "route_status": getattr(route, "route_status", None),
                "start_time": getattr(route, "start_time", None),
                "end_time": getattr(route, "end_time", None),
                "created_at": route.created_at.isoformat() if route.created_at else None,
                # "updated_at": route.updated_at.isoformat() if route.updated_at else None,
                "stops": [
                    {
                        "stop_id": str(stop.stop_id),
                        "route_id": str(stop.route_id),
                        "order_id": str(stop.order_id) if stop.order_id else None,
                        "stop_sequence": stop.stop_sequence,
                        "stop_type": stop.stop_type,
                        "latitude": stop.address_latitude,
                        "longitude": stop.address_longitude,
                        "estimated_arrival_time": getattr(stop, "estimated_arrival_time", None),
                        "estimated_departure_time": getattr(stop, "estimated_departure_time", None),
                        "actual_arrival_time": getattr(stop, "actual_arrival_time", None),
                        "actual_departure_time": getattr(stop, "actual_departure_time", None),
                        "stop_status": getattr(stop, "stop_status", None),
                        "created_at": stop.created_at.isoformat() if stop.created_at else None,
                        # "updated_at": stop.updated_at.isoformat() if stop.updated_at else None,
                    }
                    for stop in stops
                ]
            }
            result.append(route_dict)
        
        logger.info(f"✅ Fetched {len(result)} optimized routes")
        return result
    except Exception as e:
        log_exception(logger, "❌ Error fetching optimized routes", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch routes: {str(e)}")