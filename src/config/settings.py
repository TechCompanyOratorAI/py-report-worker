"""
Report Worker Configuration Settings

Loads configuration from environment variables with defaults
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Settings:
    """Configuration settings for report worker"""
    
    # Worker Configuration
    WORKER_ID = os.getenv('WORKER_ID', 'report-worker-1')
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '5'))
    MAX_MESSAGES = int(os.getenv('MAX_MESSAGES', '1'))
    WAIT_TIME_SECONDS = int(os.getenv('WAIT_TIME_SECONDS', '20'))
    
    # AWS Configuration
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'ap-southeast-1')
    AWS_SQS_REPORT_QUEUE_URL = os.getenv('AWS_SQS_REPORT_QUEUE_URL')
    
    # Database Configuration (MySQL)
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', '3306'))
    DB_NAME = os.getenv('DB_DATABASE_NAME', 'OratorAI')
    DB_USER = os.getenv('DB_USERNAME')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_SSL = os.getenv('DB_SSL', 'true').lower() == 'true'
    
    # Webhook Configuration
    WEBHOOK_BASE_URL = os.getenv('WEBHOOK_URL', 'http://localhost:8080')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    
    # Analysis Configuration
    SIMILARITY_THRESHOLD = float(os.getenv('SIMILARITY_THRESHOLD', '0.5'))
    RELEVANCE_THRESHOLD = float(os.getenv('RELEVANCE_THRESHOLD', '0.5'))
    ALIGNMENT_THRESHOLD = float(os.getenv('ALIGNMENT_THRESHOLD', '0.5'))
    
    # AI Configuration (Gemini)
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    
    # Logging Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    @classmethod
    def validate(cls):
        """Validate required settings"""
        required_settings = [
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY', 
            'AWS_SQS_REPORT_QUEUE_URL',
            'DB_USER',
            'DB_PASSWORD'
        ]
        
        missing = []
        for setting in required_settings:
            if not getattr(cls, setting):
                missing.append(setting)
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True

# Create settings instance
settings = Settings()
