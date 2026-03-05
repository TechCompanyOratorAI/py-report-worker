"""
Logger utility for py-report-worker
"""

import logging
import sys
import os

from src.config.settings import settings

# Create logger
logger = logging.getLogger('py-report-worker')

# Configure handler
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(handler)
logger.setLevel(settings.LOG_LEVEL)

def get_logger(name: str) -> logging.Logger:
    """Get logger instance"""
    return logging.getLogger(name)
