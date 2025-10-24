# app/utils/logger.py
import logging
import os
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class Logger:
    def __init__(self):
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Logger configuration
        self.logger = logging.getLogger("delivery_route_optimizer")
        self.logger.setLevel(logging.DEBUG if os.getenv("DEBUG", "False").lower() == "true" else logging.INFO)

        # Prevent duplicate handlers
        if self.logger.handlers:
            return

        # Log format with traceback support
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
        )

        # File handler (rotates daily)
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / "route_optimizer.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger


# Create singleton instance
logger = Logger().get_logger()
logger.info("✅ Logger initialized for Route Optimizer Service")


def log_exception(logger_instance, message: str, exc: Exception):
    """Helper function to log exceptions with full traceback"""
    logger_instance.error(f"{message}: {str(exc)}")
    logger_instance.error(f"Traceback: {traceback.format_exc()}")
