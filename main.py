"""
Report Worker - Main Entry Point

This worker polls messages from AWS SQS report queue, performs analysis
on transcript segments against slides and topic, saves results to database
(SegmentAnalyses and AnalysisResults tables), then sends webhook to API.
"""

import sys
import signal
import time
from typing import Dict, Any

# Add src to path
sys.path.insert(0, 'src')

from config.settings import settings
from utils.logger import get_logger
from utils.exceptions import (
    ReportWorkerError,
    DatabaseError,
    SQSError,
    WebhookError,
    AnalysisError
)

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
        print("DEBUG: start() called", file=sys.stderr, flush=True)
        
        logger.info("=" * 80)
        logger.info(f"🚀 Starting {self.worker_name}")
        logger.info("=" * 80)
        logger.info(f"📊 Configuration:")
        logger.info(f"   - SQS Queue: {settings.AWS_SQS_REPORT_QUEUE_URL}")
        logger.info(f"   - Poll Interval: {settings.POLL_INTERVAL}s")
        logger.info(f"   - Max Messages: {settings.MAX_MESSAGES}")
        logger.info(f"   - Similarity Threshold: {settings.SIMILARITY_THRESHOLD}")
        logger.info(f"   - Relevance Threshold: {settings.RELEVANCE_THRESHOLD}")
        logger.info(f"   - Alignment Threshold: {settings.ALIGNMENT_THRESHOLD}")
        logger.info("=" * 80)
        
        # Validate configuration
        try:
            print("DEBUG: Validating configuration...", file=sys.stderr, flush=True)
            settings.validate()
            logger.info("✅ Configuration validated")
            print("DEBUG: Configuration validated", file=sys.stderr, flush=True)
        except ValueError as e:
            logger.error(f"❌ Configuration validation failed: {e}")
            print(f"ERROR: Configuration validation failed: {e}", file=sys.stderr, flush=True)
            sys.exit(1)
        
        # Initialize services
        try:
            print("DEBUG: About to initialize services...", file=sys.stderr, flush=True)
            self._initialize_services()
            print("DEBUG: Services initialized successfully", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"ERROR: During InitializationError: {e}", file=sys.stderr, flush=True)
            logger.error(f"❌ Fatal error during initialization: {e}", exc_info=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            self.stop()
            sys.exit(1)
        
        print("DEBUG: Setting running = True", file=sys.stderr, flush=True)
        self.running = True
        
        print("DEBUG: About to enter polling loop...", file=sys.stderr, flush=True)
        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("⚠️ Received keyboard interrupt")
            self.stop()
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}", exc_info=True)
            print(f"ERROR: Fatal error in run_loop: {e}", file=sys.stderr, flush=True)
            self.stop()
            sys.exit(1)
    
    def _initialize_services(self):
        """Initialize all services"""
        try:
            logger.info("🔧 Initializing services...")
            print("DEBUG: [1/5] Getting SQS service...", file=sys.stderr, flush=True)
            
            # SQS Service
            self.sqs_service = get_sqs_service()
            print("DEBUG: [2/5] SQS service ready", file=sys.stderr, flush=True)
            logger.info("   ✅ SQS Service ready")
            
            print("DEBUG: [3/5] Getting Database service...", file=sys.stderr, flush=True)
            # Database Service
            self.database_service = get_database_service()
            print("DEBUG: [4/5] Database service ready", file=sys.stderr, flush=True)
            logger.info("   ✅ Database Service ready")
            
            print("DEBUG: [5/5] Getting Webhook service...", file=sys.stderr, flush=True)
            # Webhook Service
            self.webhook_service = get_webhook_service()
            print("DEBUG: [6/5] Webhook service ready", file=sys.stderr, flush=True)
            
            # Test webhook connectivity
            if self.webhook_service.test_connection():
                logger.info("   ✅ Webhook Service ready")
            else:
                logger.warning("   ⚠️ Webhook Service initialized but endpoint not reachable")
            print("DEBUG: [7/5] About to get Report Analysis service...", file=sys.stderr, flush=True)
            
            # Report Analysis Service
            self.report_service = get_report_analysis_service(self.database_service)
            print("DEBUG: [8/5] Report Analysis service ready", file=sys.stderr, flush=True)
            logger.info("   ✅ Report Analysis Service ready")
            
            logger.info("✅ All services initialized successfully")
            print("DEBUG: All services initialized!", file=sys.stderr, flush=True)
            
        except Exception as e:
            error_msg = f"Failed to initialize services: {e}"
            print(f"DEBUG ERROR: {error_msg}", file=sys.stderr, flush=True)
            logger.error(f"❌ {error_msg}", exc_info=True)
            import traceback
            print("\n=== TRACEBACK ===", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            print("=== END TRACEBACK ===\n", file=sys.stderr, flush=True)
            raise
    
    def _run_loop(self):
        """Main worker loop - poll and process messages"""
        print("[RUNNING] ENTERED WORKER LOOP - polling SQS...")
        logger.info("🔄 Worker started, polling for messages...")
        logger.info("")
        
        poll_count = 0
        
        while self.running:
            try:
                # Poll SQS for messages
                messages = self.sqs_service.poll_messages(
                    max_messages=settings.MAX_MESSAGES,
                    wait_time_seconds=settings.WAIT_TIME_SECONDS
                )
                
                poll_count += 1
                if not messages:
                    # No messages - continue polling
                    if poll_count % 3 == 0:  # Log every 3rd poll (roughly every 60 seconds)
                        logger.info(f"⏳ Waiting for messages... (poll #{poll_count})")
                    continue
                
                # Reset poll count when messages arrive
                poll_count = 0
                
                # Process each message
                for message in messages:
                    self._process_message(message)
                
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"❌ Error in worker loop: {e}", exc_info=True)
                time.sleep(settings.POLL_INTERVAL)
    
    def _process_message(self, message: SQSMessage):
        """
        Process a single SQS message
        
        Args:
            message: SQSMessage object
        """
        job_id = message.job_id
        presentation_id = message.presentation_id
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"🎯 Processing Report Job {job_id}")
        logger.info("=" * 80)
        logger.info(f"   - Presentation ID: {presentation_id}")
        logger.info(f"   - Message ID: {message.message_id}")
        
        # Track processing time
        start_time = time.time()
        
        try:
            # Process the report job
            result = self._process_report_job(
                job_id=job_id,
                presentation_id=presentation_id,
                metadata=message.metadata,
                start_time=start_time
            )
            
            # Calculate processing time
            processing_time = time.time() - start_time
            result['metadata']['processingTime'] = round(processing_time, 2)
            result['metadata']['processingTimeSeconds'] = round(processing_time, 2)
            
            # Send success webhook
            logger.info(f"📤 Sending success webhook...")
            self.webhook_service.send_report_complete(
                job_id=job_id,
                presentation_id=presentation_id,
                segment_analyses=result['segmentAnalyses'],
                overall_scores=result['overallScores'],
                metadata=result['metadata']
            )
            
            # Delete message from queue (success)
            logger.info(f"🗑️ Deleting message from queue...")
            self.sqs_service.delete_message(message)
            
            # Update statistics
            self.jobs_processed += 1
            self.jobs_succeeded += 1
            
            logger.info("=" * 80)
            logger.info(f"✅ Job {job_id} completed successfully in {processing_time:.2f}s")
            logger.info(f"📊 Stats: {self.jobs_succeeded} succeeded, {self.jobs_failed} failed, {self.jobs_processed} total")
            logger.info("=" * 80)
            logger.info("")
            
        except Exception as e:
            # Calculate processing time
            processing_time = time.time() - start_time
            
            logger.error("=" * 80)
            logger.error(f"❌ Job {job_id} failed after {processing_time:.2f}s")
            logger.error(f"❌ Error: {e}", exc_info=True)
            logger.error("=" * 80)
            
            # Send failure webhook
            try:
                logger.warning(f"📤 Sending failure webhook...")
                self.webhook_service.send_report_failed(
                    job_id=job_id,
                    presentation_id=presentation_id,
                    error_message=str(e),
                    error_details={
                        'error_type': type(e).__name__,
                        'processing_time': round(processing_time, 2)
                    }
                )
            except Exception as webhook_error:
                logger.error(f"❌ Failed to send failure webhook: {webhook_error}")
            
            # Update statistics
            self.jobs_processed += 1
            self.jobs_failed += 1
            
            # DO NOT delete message - allow retry after visibility timeout
            logger.warning(f"⚠️ Message NOT deleted - will retry after visibility timeout")
            logger.info(f"📊 Stats: {self.jobs_succeeded} succeeded, {self.jobs_failed} failed, {self.jobs_processed} total")
            logger.info("")
    
    def _process_report_job(
        self,
        job_id: int,
        presentation_id: int,
        metadata: Dict[str, Any],
        start_time: float
    ) -> Dict[str, Any]:
        """
        Process report generation job
        
        Args:
            job_id: Job ID
            presentation_id: Presentation ID
            metadata: Job metadata
            start_time: Start time for calculating processing duration
            
        Returns:
            Dictionary with analysis results
        """
        # Step 1: Get presentation data
        logger.info(f"📥 Step 1/4: Loading presentation data...")
        presentation_data = self.database_service.get_presentation_data(presentation_id)
        
        if not presentation_data:
            raise DatabaseError(f"Presentation {presentation_id} not found or incomplete")
        
        logger.info(f"   - Title: {presentation_data.title}")
        logger.info(f"   - Topic: {presentation_data.topic_name}")
        logger.info(f"   - Transcript segments: {len(presentation_data.transcript_segments)}")
        logger.info(f"   - Slides: {len(presentation_data.slides)}")
        
        if not presentation_data.transcript_segments:
            raise AnalysisError("No transcript segments found for analysis")
        
        # Step 2: Perform analysis
        logger.info(f"🔍 Step 2/4: Performing segment analysis...")
        
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
        
        # Step 3: Save segment analyses to database
        logger.info(f"💾 Step 3/4: Saving segment analyses to database...")
        
        for i, analysis in enumerate(segment_analyses_obj):
            # Get slide_id for best matching slide
            slide_id = None
            if analysis.best_matching_slide > 0:
                for slide in presentation_data.slides:
                    if slide.get('slideNumber') == analysis.best_matching_slide:
                        slide_id = slide.get('slideId')
                        break
            
            # Estimate processing time per segment (in milliseconds)
            segment_processing_time = time.time() - start_time
            processing_time_ms = int((segment_processing_time / len(segment_analyses_obj)) * 1000)
            
            self.database_service.save_segment_analysis(analysis, slide_id, processing_time_ms)
        
        logger.info(f"   - Saved {len(segment_analyses)} segment analyses")
        
        # Step 4: Save overall results to database
        logger.info(f"💾 Step 4/4: Saving overall results to database...")
        
        result_id = self.database_service.save_analysis_results(
            presentation_id, 
            overall_scores_obj,
            processing_time_seconds=round(segment_processing_time, 2),
            ai_model_version="report-worker-v1"
        )
        logger.info(f"   - Saved AnalysisResults: resultId={result_id}")
        
        # Format metadata
        result_metadata = {
            'totalSegments': len(segment_analyses),
            'totalSlides': len(presentation_data.slides),
            'topicName': presentation_data.topic_name,
            'topicDescription': presentation_data.topic_description,
            'jobId': job_id,
            'resultId': result_id,
            'aiModelVersion': 'report-worker-v1',
            'processingTimeSeconds': round(segment_processing_time, 2)
        }
        
        logger.info(f"✅ Report generation complete:")
        logger.info(f"   - Analyzed segments: {len(segment_analyses)}")
        logger.info(f"   - Content relevance: {overall_scores['contentRelevance']:.2f}")
        logger.info(f"   - Semantic similarity: {overall_scores['semanticSimilarity']:.2f}")
        logger.info(f"   - Slide alignment: {overall_scores['slideAlignment']:.2f}")
        
        return {
            'segmentAnalyses': segment_analyses,
            'overallScores': overall_scores,
            'metadata': result_metadata
        }
    
    def stop(self):
        """Stop the worker gracefully"""
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"🛑 Stopping {self.worker_name}...")
        logger.info(f"📊 Final Stats:")
        logger.info(f"   - Jobs succeeded: {self.jobs_succeeded}")
        logger.info(f"   - Jobs failed: {self.jobs_failed}")
        logger.info(f"   - Jobs total: {self.jobs_processed}")
        logger.info("=" * 80)
        self.running = False
        
        # Close database connection
        if self.database_service:
            self.database_service.close()


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"⚠️ Received signal {signum}")
    sys.exit(0)


def main():
    """Main entry point"""
    print("[RUNNING] APP IS RUNNING...")
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and start worker
    worker = ReportWorker()
    worker.start()

if __name__ == "__main__":
    main()
