"""
Webhook service for sending results back to the API
"""

import json
import os
import hmac
import hashlib
import time
import requests
from typing import Dict, Any, List

from src.config.settings import settings
from src.utils.logger import get_logger
from src.utils.exceptions import WebhookError

logger = get_logger(__name__)

class WebhookService:
    """Service for sending webhooks"""
    
    def __init__(self):
        self.base_url = os.getenv('WEBHOOK_URL', 'http://localhost:8080/api/v1')
        self.secret = os.getenv('WEBHOOK_SECRET')
        self.timeout = 300
        
    def _generate_signature(self, payload: str) -> str:
        """Generate HMAC signature for webhook payload"""
        if not self.secret:
            return ""
        return hmac.new(
            self.secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _send_webhook(self, endpoint: str, payload: Dict[str, Any]) -> bool:
        """
        Send webhook request
        
        Args:
            endpoint: Webhook endpoint path
            payload: Payload to send
            
        Returns:
            True if successful
        """
        url = f"{self.base_url}{endpoint}"
        
        # Generate signature
        payload_str = json.dumps(payload, ensure_ascii=False)
        signature = self._generate_signature(payload_str)
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        # Add authorization header if secret is configured
        if self.secret:
            headers['Authorization'] = f'Bearer {self.secret}'
        
        if signature:
            headers['X-Webhook-Signature'] = signature
        
        try:
            response = requests.post(
                url,
                data=payload_str,
                headers=headers,
                timeout=self.timeout
            )

            if response.status_code >= 200 and response.status_code < 300:
                logger.info(f"Webhook sent successfully to {endpoint}")
                return True
            else:
                logger.warning(f"Webhook failed: {response.status_code} - {response.text}")
                return False

        except requests.RequestException as e:
            logger.error(f"Failed to send webhook: {e}")
            return False

    def _send_webhook_with_retry(self, endpoint: str, payload: Dict[str, Any], max_retries: int = 3, retry_delay: int = 5) -> bool:
        """
        Send webhook request with retry logic.

        Args:
            endpoint: Webhook endpoint path
            payload: Payload to send
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            True if successful
        """
        for attempt in range(1, max_retries + 1):
            if self._send_webhook(endpoint, payload):
                return True
            if attempt < max_retries:
                logger.warning(f"Webhook retry {attempt}/{max_retries} in {retry_delay}s...")
                time.sleep(retry_delay)
        logger.error(f"Webhook failed after {max_retries} attempts")
        return False
    
    def send_report_complete(
        self,
        job_id: int,
        presentation_id: int,
        report_id: int = None,
        segment_analyses: List[Dict[str, Any]] = None,
        overall_scores: Dict[str, Any] = None,
        rubric_scores: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        report_body: Dict[str, Any] = None
    ) -> bool:
        """
        Send report completion webhook

        Args:
            job_id: Job ID
            presentation_id: Presentation ID
            report_id: AIReport ID
            segment_analyses: List of segment analysis results
            overall_scores: Overall scores
            rubric_scores: Rubric-based scores
            metadata: Additional metadata
            report_body: Structured report body (summary, strengths, weaknesses, suggestions)

        Returns:
            True if successful
        """
        payload = {
            'jobId': job_id,
            'presentationId': presentation_id,
            'reportId': report_id,
            'status': 'success',  # Consistent with ASR/Semantic workers ('done' was non-standard)
            'segmentAnalyses': segment_analyses or [],
            'overallScores': overall_scores or {},
            'rubricScores': rubric_scores or {},
            'metadata': metadata or {},
            'reportBody': report_body or {}
        }

        return self._send_webhook_with_retry('/webhooks/report-complete', payload)
    
    def send_report_failed(
        self,
        job_id: int,
        presentation_id: int,
        report_id: int = None,
        error_message: str = None,
        error_details: Dict[str, Any] = None
    ) -> bool:
        """
        Send report failure webhook.
        Node API only has /webhooks/report-complete; it accepts status='failed' there.
        """
        payload = {
            'jobId': job_id,
            'presentationId': presentation_id,
            'reportId': report_id,
            'status': 'failed',
            'error': error_message,
            'errorDetails': error_details or {}
        }
        return self._send_webhook_with_retry('/webhooks/report-complete', payload)
    
    def test_connection(self) -> bool:
        """Test webhook connectivity"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False


# Singleton instance
_webhook_service = None

def get_webhook_service() -> WebhookService:
    """Get webhook service singleton"""
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = WebhookService()
    return _webhook_service
