from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

from app.routes import optimizer
from app.database import engine, Base
from app.utils.logger import logger

# Load environment variables
load_dotenv()

logger.info("🚀 Starting Route Optimizer Service...")

# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created successfully")
except Exception as e:
    logger.error(f"❌ Failed to create database tables: {str(e)}")
    raise

app = FastAPI(
    title="Route Optimizer Service",
    description="Microservice for delivery route optimization using VRP algorithms with real-time traffic data",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(optimizer.router, prefix="/api/v1")

@app.on_event("startup")
async def startup_event():
    logger.info("✅ Route Optimizer Service started successfully")
    logger.info(f"📍 Service URL: http://{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', 8003)}")
    logger.info(f"📚 API Docs: http://{os.getenv('HOST', 'localhost')}:{os.getenv('PORT', 8003)}/docs")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Route Optimizer Service shutting down...")

@app.get("/")
async def root():
    logger.debug("Root endpoint called")
    return {
        "message": "Route Optimizer Service is running",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    logger.debug("Health check endpoint called")
    try:
        return {
            "status": "healthy",
            "service": "route-optimizer",
            "traffic_service_url": os.getenv("TRAFFIC_SERVICE_URL"),
            "order_service_url": os.getenv("ORDER_SERVICE_URL")
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "service": "route-optimizer",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8003)),
        reload=True
    )
