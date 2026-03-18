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
    """SQS message structure - matches oratorai-report-queue payload"""
    message_id: str
    receipt_handle: str
    job_id: int
    presentation_id: int
    report_id: int = None  # AIReport ID from Node API (optional)
    class_id: int = None  # Class ID (optional)
    rubric_data: list = None  # Rubric criteria from Node API (optional)
    settings: dict = None  # AI settings (optional)
    metadata: Dict[str, Any] = None
    queue_type: str = None  # e.g. "report"
    sent_at: str = None
    version: str = None

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
                    raw_body = msg['Body']
                    body = json.loads(raw_body)
                    # Handle SNS-wrapped message (Body may be JSON with 'Message' containing payload)
                    if isinstance(body, dict) and 'Message' in body:
                        body = json.loads(body['Message']) if isinstance(body['Message'], str) else body['Message']

                    queue_type = body.get('queueType')
                    if queue_type is not None and queue_type != 'report':
                        logger.debug(f"Skipping non-report message: queueType={queue_type}")
                        continue

                    job_id = body.get('jobId')
                    presentation_id = body.get('presentationId')
                    if job_id is None or presentation_id is None:
                        logger.warning(f"Missing jobId or presentationId in message: {body}")
                        continue

                    sqs_message = SQSMessage(
                        message_id=msg['MessageId'],
                        receipt_handle=msg['ReceiptHandle'],
                        job_id=job_id,
                        presentation_id=presentation_id,
                        report_id=body.get('reportId'),
                        class_id=body.get('classId'),
                        rubric_data=body.get('rubricData'),
                        settings=body.get('settings'),
                        metadata=body,
                        queue_type=queue_type,
                        sent_at=body.get('sentAt'),
                        version=body.get('version')
                    )
                    sqs_messages.append(sqs_message)
                    logger.debug(
                        f"Received report message: id={sqs_message.message_id}, jobId={sqs_message.job_id}, "
                        f"presentationId={sqs_message.presentation_id}, reportId={sqs_message.report_id}"
                    )
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(f"Invalid message format: {e}")
                    continue
            
            return sqs_messages
            
        except (ClientError, BotoCoreError) as e:
            raise SQSError(f"Failed to poll messages: {e}")
    
    def change_message_visibility(self, message: SQSMessage, visibility_timeout: int) -> bool:
        """
        Extend visibility timeout so message is not re-delivered while processing.
        Use this when processing takes longer than queue's default (e.g. 8 seconds).

        Args:
            message: SQSMessage object
            visibility_timeout: Seconds the message stays hidden (e.g. 300 for 5 min)

        Returns:
            True if successful
        """
        try:
            self.client.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=message.receipt_handle,
                VisibilityTimeout=visibility_timeout
            )
            logger.debug(f"Extended visibility for message {message.message_id} to {visibility_timeout}s")
            return True
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to change message visibility: {e}")
            return False

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
