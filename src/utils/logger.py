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
if not logger.handlers:
    logger.addHandler(handler)
logger.setLevel(settings.LOG_LEVEL)
logger.propagate = False

def get_logger(name: str) -> logging.Logger:
    """Get logger instance"""
    if not name or name == 'py-report-worker':
        return logger

    child_name = name if name.startswith('py-report-worker') else f'py-report-worker.{name}'
    child_logger = logging.getLogger(child_name)
    child_logger.setLevel(settings.LOG_LEVEL)
    child_logger.propagate = True
    return child_logger
