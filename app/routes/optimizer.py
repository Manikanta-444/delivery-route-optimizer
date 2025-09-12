from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import logging

from app.database import get_db
from app.models.optimization import OptimizationJob, OptimizedRoute, RouteStop
from app.schemas.optimization import (
    OptimizationRequest, OptimizationJobResponse, OptimizationSummary,
    LocationPoint, OptimizationConstraints
)
from app.services.vrp_solver import VRPSolver
from app.services.order_client import OrderClient
from app.services.traffic_client import TrafficClient

router = APIRouter(prefix="/routes", tags=["route-optimization"])
logger = logging.getLogger(__name__)

order_client = OrderClient()
traffic_client = TrafficClient()


@router.post("/optimize", response_model=dict)
async def optimize_routes(
        request: OptimizationRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    """Start route optimization job"""

    # Validate constraints
    if len(request.order_ids) > 100:
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

    # Add to background task
    background_tasks.add_task(
        process_optimization,
        str(job.job_id),
        [str(oid) for oid in request.order_ids],
        request.constraints.dict(),
        request.use_traffic_data,
        db
    )

    return {
        "job_id": job.job_id,
        "status": "PENDING",
        "message": "Optimization job started",
        "estimated_completion_time": datetime.now() + timedelta(minutes=2)
    }


@router.get("/jobs/{job_id}", response_model=OptimizationJobResponse)
def get_optimization_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get optimization job status and results"""
    job = db.query(OptimizationJob).filter(OptimizationJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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

    return OptimizationSummary(
        total_jobs=total_jobs,
        pending_jobs=pending_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        avg_computation_time_seconds=avg_computation_time,
        total_routes_optimized=total_routes
    )


@router.delete("/jobs/{job_id}")
def delete_optimization_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete optimization job and all related data"""
    job = db.query(OptimizationJob).filter(OptimizationJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(job)
    db.commit()
    return {"message": "Job deleted successfully"}


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
        job = db.query(OptimizationJob).filter(OptimizationJob.job_id == uuid.UUID(job_id)).first()
        if job:
            job.job_status = "FAILED"
            job.error_message = str(e)
            job.completed_at = datetime.now()
            db.commit()
