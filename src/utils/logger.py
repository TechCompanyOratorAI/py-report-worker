"""
Logger utility for py-report-worker
"""

import logging
import sys
import os
import coloredlogs

from src.config.settings import settings

# Create logger
logger = logging.getLogger('py-report-worker')

# Configure colored logs
coloredlogs.install(
    level=settings.LOG_LEVEL,
    logger=logger,
    fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_logger(name: str) -> logging.Logger:
    """Get logger instance"""
    return logging.getLogger(name)
