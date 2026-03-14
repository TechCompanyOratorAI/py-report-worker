"""
Report Worker - Main Entry Point

Polls messages from AWS SQS queue, performs analysis on transcript segments,
saves results to database, then sends webhook to API.
"""

import sys
import signal
import time
from typing import Dict, Any

# Add src to path
sys.path.insert(0, 'src')

from config.settings import settings
from utils.logger import get_logger
from utils.exceptions import DatabaseError, AnalysisError

# Import services
from services.sqs_service import get_sqs_service, SQSMessage
from services.database_service import get_database_service
from services.webhook_service import get_webhook_service
from services.report_analysis_service import get_report_analysis_service

logger = get_logger(__name__)


class ReportWorker:
    """Main Report Worker class"""
    
    def __init__(self):
        self.running = False
        self.worker_name = f"ReportWorker-{settings.WORKER_ID}"
        
        # Initialize services
        self.sqs_service = None
        self.database_service = None
        self.webhook_service = None
        self.report_service = None
        
        # Statistics
        self.jobs_processed = 0
        self.jobs_succeeded = 0
        self.jobs_failed = 0
    
    def start(self):
        """Start the worker"""
        logger.info(f"🚀 Starting {settings.WORKER_ID}")
        logger.info(f"   - SQS Queue: {settings.AWS_SQS_REPORT_QUEUE_URL}")
        
        # Validate configuration
        try:
            settings.validate()
            logger.info("✅ Configuration validated")
        except ValueError as e:
            logger.error(f"❌ Configuration error: {e}")
            sys.exit(1)
        
        # Initialize services
        self._initialize_services()
        self.running = True
        
        # Start polling loop
        self._run_loop()
    
    def _initialize_services(self):
        """Initialize all services"""
        logger.info("🔧 Initializing services...")
        
        self.sqs_service = get_sqs_service()
        self.database_service = get_database_service()
        self.webhook_service = get_webhook_service()
        
        # Test webhook connectivity
        if self.webhook_service.test_connection():
            logger.info("   ✅ Webhook Service ready")
        
        # Report Analysis Service
        self.report_service = get_report_analysis_service(self.database_service)
        logger.info("✅ All services initialized")
    
    def _run_loop(self):
        """Main worker loop - poll and process messages"""
        logger.info("🔄 Worker started, polling for messages...")
        
        while self.running:
            try:
                messages = self.sqs_service.poll_messages(
                    max_messages=settings.MAX_MESSAGES,
                    wait_time_seconds=settings.WAIT_TIME_SECONDS
                )
                
                if not messages:
                    continue
                    
                for message in messages:
                    self._process_message(message)
            
            except KeyboardInterrupt:
                logger.info("⚠️ Received keyboard interrupt")
                self.stop()
            except Exception as e:
                logger.error(f"❌ Error in worker loop: {e}")
                time.sleep(settings.POLL_INTERVAL)
    
    def _process_message(self, message: SQSMessage):
        """Process a single SQS message"""
        job_id = message.job_id
        presentation_id = message.presentation_id
        
        logger.info(f"🎯 Processing Job {job_id} - Presentation {presentation_id}")
        
        start_time = time.time()
        
        try:
            result = self._process_report_job(
                job_id=job_id,
                presentation_id=presentation_id,
                metadata=message.metadata,
                start_time=start_time
            )
            
            processing_time = time.time() - start_time
            result['metadata']['processingTime'] = round(processing_time, 2)
            
            # Send success webhook
            self.webhook_service.send_report_complete(
                job_id=job_id,
                presentation_id=presentation_id,
                segment_analyses=result['segmentAnalyses'],
                overall_scores=result['overallScores'],
                metadata=result['metadata']
            )
            
            # Delete message from queue
            self.sqs_service.delete_message(message)
            
            # Update statistics
            self.jobs_processed += 1
            self.jobs_succeeded += 1
            
            logger.info(f"✅ Job {job_id} completed in {processing_time:.2f}s")
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"❌ Job {job_id} failed: {e}")
            
            # Send failure webhook
            try:
                self.webhook_service.send_report_failed(
                    job_id=job_id,
                    presentation_id=presentation_id,
                    error_message=str(e)
                )
            except Exception as webhook_error:
                logger.error(f"❌ Failed to send webhook: {webhook_error}")
            
            self.jobs_processed += 1
            self.jobs_failed += 1
    
    def _process_report_job(
        self,
        job_id: int,
        presentation_id: int,
        metadata: Dict[str, Any],
        start_time: float
    ) -> Dict[str, Any]:
        """Process report generation job"""
        
        # Step 1: Get presentation data
        logger.info(f"📥 Loading presentation data...")
        presentation_data = self.database_service.get_presentation_data(presentation_id)
        
        if not presentation_data:
            raise DatabaseError(f"Presentation {presentation_id} not found")
        
        if not presentation_data.transcript_segments:
            raise AnalysisError("No transcript segments found")
        
        # Step 2: Perform analysis
        logger.info(f"🔍 Analyzing segments...")
        segment_analyses_obj, overall_scores_obj = self.report_service.analyze_presentation(presentation_data)
        
        # Convert to API format
        segment_analyses = []
        for analysis in segment_analyses_obj:
            segment_analyses.append({
                'segmentId': analysis.segment_id,
                'relevanceScore': analysis.relevance_score,
                'semanticScore': analysis.semantic_score,
                'alignmentScore': analysis.alignment_score,
                'issues': analysis.issues,
                'suggestions': analysis.suggestions,
                'topicKeywordsFound': analysis.topic_keywords_found,
                'bestMatchingSlide': analysis.best_matching_slide,
                'expectedSlideNumber': analysis.expected_slide_number,
                'timingDeviation': analysis.timing_deviation
            })
        
        overall_scores = {
            'contentRelevance': overall_scores_obj.content_relevance,
            'semanticSimilarity': overall_scores_obj.semantic_similarity,
            'slideAlignment': overall_scores_obj.slide_alignment,
            'overallScore': overall_scores_obj.overall_score
        }

        # Step 3: Generate AI feedback
        logger.info(f"🤖 Generating AI feedback...")
        
        try:
            # Use segment analyses from memory instead of reading from database
            if segment_analyses and overall_scores:
                feedback_result = self.report_service.generate_feedback(
                    presentation_title=presentation_data.title,
                    topic_name=presentation_data.topic_name,
                    topic_description=presentation_data.topic_description or "",
                    segment_analyses=segment_analyses,
                    overall_scores=overall_scores,
                    course_name=presentation_data.course_name,
                    course_description=presentation_data.course_description,
                    topic_requirements=presentation_data.topic_requirements
                )
                
                self.database_service.save_feedback(
                    presentation_id=presentation_id,
                    rating=feedback_result['overall_score'],
                    comments=feedback_result['comments'],
                    feedback_type=feedback_result.get('feedback_type', 'ai_report'),
                    reviewer_id=None,
                    is_visible_to_student=True
                )
        except Exception as e:
            logger.error(f"   - Failed to generate feedback: {e}")
        
        # Step 4: Generate Teamwork Analysis feedback
        logger.info(f"👥 Analyzing teamwork...")
        
        try:
            transcript_data = self.database_service.get_transcript_with_speakers(presentation_id)
            
            if transcript_data["segments"] and len(transcript_data["speakers"]) >= 2:
                teamwork_result = self.report_service.analyze_teamwork(transcript_data)
                
                # Save teamwork feedback
                self.database_service.save_feedback(
                    presentation_id=presentation_id,
                    rating=teamwork_result.overall_teamwork_score,
                    comments=teamwork_result.feedback,
                    feedback_type='teamwork',  # Different feedback type
                    reviewer_id=None,
                    is_visible_to_student=True
                )
                
                logger.info(f"   ✅ Teamwork analysis saved: score={teamwork_result.overall_teamwork_score:.2f}")
            else:
                logger.info(f"   - Skipped teamwork analysis: not enough speakers ({len(transcript_data['speakers'])})")
        except Exception as e:
            logger.error(f"   - Failed to analyze teamwork: {e}")
        
        return {
            'segmentAnalyses': segment_analyses,
            'overallScores': overall_scores,
            'metadata': {
                'totalSegments': len(segment_analyses),
                'totalSlides': len(presentation_data.slides),
                'jobId': job_id
            }
        }
    
    def stop(self):
        """Stop the worker gracefully"""
        logger.info(f"🛑 Stopping {self.worker_name}...")
        self.running = False
        
        if self.database_service:
            self.database_service.close()


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    sys.exit(0)


def main():
    """Main entry point"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    worker = ReportWorker()
    worker.start()


if __name__ == "__main__":
    main()
