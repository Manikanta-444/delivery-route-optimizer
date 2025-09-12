import requests
import os
from typing import Dict, List, Optional
import uuid
import logging

logger = logging.getLogger(__name__)

class OrderClient:
    def __init__(self):
        self.base_url = os.getenv("ORDER_SERVICE_URL", "http://localhost:8001/api/v1")
        self.timeout = 10

    def get_order_details(self, order_id: uuid.UUID) -> Optional[Dict]:
        """Get order details from order service"""
        try:
            response = requests.get(
                f"{self.base_url}/orders/{order_id}",
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def get_multiple_orders(self, order_ids: List[uuid.UUID]) -> List[Dict]:
        """Get multiple order details"""
        orders = []
        for order_id in order_ids:
            order = self.get_order_details(order_id)
            if order:
                orders.append(order)
        return orders

    def get_address_details(self, address_id: uuid.UUID) -> Optional[Dict]:
        """Get address details from order service"""
        try:
            response = requests.get(
                f"{self.base_url}/addresses/{address_id}",
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get address {address_id}: {e}")
            return None

    def update_order_status(self, order_id: uuid.UUID, status: str) -> bool:
        """Update order status"""
        try:
            response = requests.put(
                f"{self.base_url}/orders/{order_id}",
                json={"order_status": status},
                timeout=self.timeout
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update order {order_id}: {e}")
            return False
