"""
SQS service for polling and processing messages
"""

import json
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from src.config.settings import settings
from src.utils.logger import get_logger
from src.utils.exceptions import SQSError

logger = get_logger(__name__)

@dataclass
class SQSMessage:
    """SQS message structure"""
    message_id: str
    receipt_handle: str
    job_id: int
    presentation_id: int
    metadata: Dict[str, Any]

class SQSService:
    """Service for SQS operations"""
    
    def __init__(self):
        self.client = boto3.client(
            'sqs',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        self.queue_url = settings.AWS_SQS_REPORT_QUEUE_URL
        logger.info(f"SQS Service initialized with queue: {self.queue_url}")
    
    def poll_messages(
        self, 
        max_messages: int = 1, 
        wait_time_seconds: int = 20
    ) -> List[SQSMessage]:
        """
        Poll messages from SQS queue
        
        Args:
            max_messages: Maximum number of messages to receive
            wait_time_seconds: Long polling wait time
            
        Returns:
            List of SQSMessage objects
        """
        try:
            response = self.client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
                MessageAttributeNames=['All'],
                AttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            
            if not messages:
                return []
            
            sqs_messages = []
            for msg in messages:
                try:
                    body = json.loads(msg['Body'])
                    
                    sqs_message = SQSMessage(
                        message_id=msg['MessageId'],
                        receipt_handle=msg['ReceiptHandle'],
                        job_id=body.get('jobId'),
                        presentation_id=body.get('presentationId'),
                        metadata=body
                    )
                    sqs_messages.append(sqs_message)
                    
                    logger.debug(f"Received message: {sqs_message.message_id}, jobId={sqs_message.job_id}")
                    
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Invalid message format: {e}")
                    continue
            
            return sqs_messages
            
        except (ClientError, BotoCoreError) as e:
            raise SQSError(f"Failed to poll messages: {e}")
    
    def delete_message(self, message: SQSMessage) -> bool:
        """
        Delete message from queue after successful processing
        
        Args:
            message: SQSMessage object
            
        Returns:
            True if successful
        """
        try:
            self.client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=message.receipt_handle
            )
            logger.debug(f"Deleted message: {message.message_id}")
            return True
            
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to delete message: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test SQS connection"""
        try:
            self.client.get_queue_url(QueueName=self.queue_url.split('/')[-1])
            return True
        except Exception as e:
            logger.error(f"SQS connection test failed: {e}")
            return False


# Singleton instance
_sqs_service = None

def get_sqs_service() -> SQSService:
    """Get SQS service singleton"""
    global _sqs_service
    if _sqs_service is None:
        _sqs_service = SQSService()
    return _sqs_service
