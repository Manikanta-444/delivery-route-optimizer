import requests
import os
from typing import Dict, List, Optional, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential
import logging

logger = logging.getLogger(__name__)


class TrafficClient:
    def __init__(self):
        self.base_url = os.getenv("TRAFFIC_SERVICE_URL", "http://localhost:8002/api/v1")
        self.timeout = 10

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_traffic_flow(self, lat: float, lng: float) -> Dict:
        """Get traffic flow data from traffic service"""
        try:
            response = requests.get(
                f"{self.base_url}/traffic/flow",
                params={"lat": lat, "lng": lng},
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Traffic service unavailable: {e}")
            # Return default traffic data
            return {
                "current_speed_kmph": 50,
                "free_flow_speed_kmph": 60,
                "congestion_level": "LOW",
                "confidence_level": 0.5
            }

    def get_route_traffic(self, waypoints: List[Dict]) -> Dict:
        """Get route traffic data for multiple waypoints"""
        try:
            response = requests.post(
                f"{self.base_url}/traffic/route",
                json={"waypoints": waypoints},
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Route traffic service unavailable: {e}")
            return {
                "total_distance_km": 0,
                "total_time_minutes": 0,
                "traffic_delay_minutes": 0
            }

    def calculate_travel_time(self, start_lat: float, start_lng: float,
                              end_lat: float, end_lng: float) -> int:
        """Calculate travel time between two points considering traffic"""
        traffic_data = self.get_traffic_flow(start_lat, start_lng)

        # Calculate distance using Haversine formula
        distance_km = self._calculate_distance(start_lat, start_lng, end_lat, end_lng)

        # Use current speed from traffic data
        speed_kmph = traffic_data.get("current_speed_kmph", 50)
        if speed_kmph == 0:
            speed_kmph = 30  # Fallback speed

        travel_time_hours = distance_km / speed_kmph
        travel_time_minutes = int(travel_time_hours * 60)

        # Add congestion delay
        congestion_level = traffic_data.get("congestion_level", "LOW")
        delay_multiplier = {
            "LOW": 1.0,
            "MODERATE": 1.2,
            "HIGH": 1.5,
            "SEVERE": 2.0
        }.get(congestion_level, 1.0)

        return max(1, int(travel_time_minutes * delay_multiplier))

    def _calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two coordinates (Haversine formula)"""
        import math

        R = 6371  # Earth's radius in kilometers

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c
