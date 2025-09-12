from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
from dotenv import load_dotenv

from app.routes import optimizer
from app.database import engine, Base

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Create tables
Base.metadata.create_all(bind=engine)

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

@app.get("/")
async def root():
    return {
        "message": "Route Optimizer Service is running",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "route-optimizer",
        "traffic_service_url": os.getenv("TRAFFIC_SERVICE_URL"),
        "order_service_url": os.getenv("ORDER_SERVICE_URL")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8003))
    )
