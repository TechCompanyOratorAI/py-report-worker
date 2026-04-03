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
        """Process a single SQS message from oratorai-report-queue"""
        job_id = message.job_id
        presentation_id = message.presentation_id
        report_id = message.report_id  # AIReport ID from Node API (optional)
        class_id = message.class_id  # Class ID (optional)
        rubric_data = message.rubric_data  # Rubric criteria (optional)
        msg_settings = message.settings  # AI settings (optional)

        # Extend visibility timeout so message is not re-delivered while we process (queue default is often 8s)
        if settings.VISIBILITY_TIMEOUT_SECONDS > 0:
            self.sqs_service.change_message_visibility(message, settings.VISIBILITY_TIMEOUT_SECONDS)

        logger.info(f"🎯 Processing Job {job_id} - Presentation {presentation_id} - Report {report_id}")
        
        start_time = time.time()
        
        try:
            result = self._process_report_job(
                job_id=job_id,
                presentation_id=presentation_id,
                report_id=report_id,
                class_id=class_id,
                rubric_data=rubric_data,
                settings=msg_settings,
                metadata=message.metadata,
                start_time=start_time
            )
            
            processing_time = time.time() - start_time
            result['metadata']['processingTime'] = round(processing_time, 2)
            
            # Send success webhook
            self.webhook_service.send_report_complete(
                job_id=job_id,
                presentation_id=presentation_id,
                report_id=result['metadata']['reportId'],
                segment_analyses=result['segmentAnalyses'],
                overall_scores=result['overallScores'],
                rubric_scores=result.get('rubricScores'),
                metadata=result['metadata'],
                report_body=result.get('reportBody')
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
                    report_id=result['metadata']['reportId'] if result and 'metadata' in result else report_id,
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
        report_id: int,
        class_id: int,
        rubric_data: list,
        settings: dict,
        metadata: Dict[str, Any],
        start_time: float
    ) -> Dict[str, Any]:
        """Process report generation job with rubric-based scoring"""
        
        # Step 1: Get presentation data
        logger.info(f"📥 Loading presentation data...")
        presentation_data = self.database_service.get_presentation_data(presentation_id)

        if not presentation_data:
            raise DatabaseError(f"Presentation {presentation_id} not found")

        if not presentation_data.transcript_segments:
            raise AnalysisError("No transcript segments found")

        # 流水线 REPORT job 的 SQS 往往不含 classId；用演示所属班级补全以便查询 ClassRubricCriteria
        effective_class_id = class_id if class_id is not None else presentation_data.class_id

        # Pipeline REPORT job SQS messages may not include reportId;
        # use ensure_ai_report_record to INSERT if missing, UPDATE if exists.
        effective_report_id = report_id
        if effective_report_id is None:
            effective_report_id = self.database_service.get_report_id_by_submission(presentation_id)
            if not effective_report_id:
                logger.warning(f"   ↳ No AIReport record for presentationId={presentation_id} — creating one now...")
                effective_report_id = self.database_service.ensure_ai_report_record(
                    submission_id=presentation_id,
                    class_id=effective_class_id
                )
                logger.info(f"   ↳ Created AIReports reportId={effective_report_id}")
            else:
                logger.info(f"   ↳ Found reportId={effective_report_id} from DB (presentationId={presentation_id})")

        if effective_report_id and effective_class_id:
            self.database_service.backfill_ai_report_class_setting_fks(
                report_id=effective_report_id,
                class_id=effective_class_id,
            )

        # Step 2: Get semantic analysis results from database
        logger.info(f"📊 Loading semantic analysis results for presentation {presentation_id}...")
        segment_analyses_data = self.database_service.get_segment_analyses_for_feedback(presentation_id)

        segment_analyses = segment_analyses_data.get('segment_analyses', [])
        overall_scores_db = segment_analyses_data.get('overall_scores')
        presentation_info = segment_analyses_data.get('presentation_info')

        logger.info(f"   - Presentation info: {presentation_info}")
        logger.info(f"   - Found {len(segment_analyses)} segment analyses")

        if not segment_analyses:
            # Log more details for debugging
            seg_count = self.database_service.get_segment_analyses_count(presentation_id)
            logger.warning(f"   - No segment analyses found! (count from DB: {seg_count})")
            # Check if presentation exists and has transcript segments
            presentation_data_check = self.database_service.get_presentation_data(presentation_id)
            if presentation_data_check:
                logger.warning(f"   - Presentation exists, has {len(presentation_data_check.transcript_segments)} transcript segments, {len(presentation_data_check.slides)} slides")
            else:
                logger.warning(f"   - Presentation {presentation_id} not found in database!")
            raise AnalysisError("No segment analyses found - semantic analysis may not be complete")
        
        # Step 3: Get speech quality data and analysis results
        logger.info(f"🎤 Loading speech quality and analysis data...")
        speech_quality = self.database_service.get_speech_quality_analysis(presentation_id)
        hesitation_patterns = self.database_service.get_hesitation_patterns(presentation_id)
        segment_speech_quality = self.database_service.get_segment_speech_quality(presentation_id)
        analysis_results = self.database_service.get_analysis_results(presentation_id)
        
        logger.info(f"   - Speech Quality: {'Yes' if speech_quality else 'No'}")
        logger.info(f"   - Hesitation Patterns: {len(hesitation_patterns) if hesitation_patterns else 0}")
        logger.info(f"   - Segment Speech Quality: {len(segment_speech_quality) if segment_speech_quality else 0}")
        logger.info(f"   - Analysis Results: {'Yes' if analysis_results else 'No'}")
        
        # Step 4: Use rubric data from message or fetch from database
        if not rubric_data and effective_class_id:
            logger.info(f"📋 Loading rubric criteria for class {effective_class_id}...")
            rubric_criteria = self.database_service.get_class_rubric_criteria(effective_class_id)
        else:
            rubric_criteria = rubric_data or []
        
        # Step 5: Calculate rubric-based scores using AI
        logger.info(f"🤖 Calculating rubric-based scores...")
        
        rubric_scores = None
        report_content = ""
        
        if rubric_criteria:
            try:
                rubric_result = self.report_service.calculate_rubric_scores(
                    presentation_title=presentation_data.title,
                    topic_name=presentation_data.topic_name,
                    topic_description=presentation_data.topic_description or "",
                    segment_analyses=segment_analyses,
                    overall_scores=overall_scores_db,
                    speech_quality=speech_quality,
                    hesitation_patterns=hesitation_patterns,
                    segment_speech_quality=segment_speech_quality,
                    analysis_results=analysis_results,
                    rubric_criteria=rubric_criteria,
                    settings=settings,
                    course_name=presentation_data.course_name,
                    course_description=presentation_data.course_description,
                    topic_requirements=presentation_data.topic_requirements
                )

                # Extract reportBody for webhook
                report_body = rubric_result.get('reportBody', {})
                report_content = rubric_result.get('report_content', '')
                overall_scores = rubric_result.get('overall_scores', overall_scores_db)

                # Build report_body for webhook (FE-friendly structured format)
                if isinstance(report_body, dict) and report_body:
                    webhook_report_body = {
                        'summary': report_body.get('summary', ''),
                        'strengths': report_body.get('strengths', []),
                        'weaknesses': report_body.get('weaknesses', []),
                        'suggestions': report_body.get('suggestions', [])
                    }
                else:
                    webhook_report_body = {}

                logger.info(f"✅ Rubric-based scoring complete")

            except Exception as e:
                logger.error(f"   - Rubric scoring failed: {e}, using fallback")
                rubric_scores = {}
                report_content = ""
                overall_scores = overall_scores_db
                webhook_report_body = {}
        else:
            logger.warning(f"   - No rubric criteria found, using basic scoring")
            overall_scores = overall_scores_db
            webhook_report_body = {}

        # Log report completion summary
        overall_score_value = overall_scores.get('overallScore', 0) if overall_scores else 0
        logger.info(f"📊 Report completed - Overall Score: {overall_score_value:.2f}/1.00")
        if rubric_scores:
            logger.info(f"   - Rubric Scores: {list(rubric_scores.keys())}")

        # Log report content
        if report_content:
            logger.info(f"📝 Report Content:\n{report_content}")
        else:
            logger.info(f"   - Report Content: (empty)")

        # Convert segment analyses to API format
        segment_analyses_api = []
        for analysis in segment_analyses:
            segment_analyses_api.append({
                'segmentId': analysis.get('segmentId'),
                'relevanceScore': analysis.get('relevanceScore'),
                'semanticScore': analysis.get('semanticScore'),
                'alignmentScore': analysis.get('alignmentScore'),
                'issues': analysis.get('issues'),
                'suggestions': analysis.get('suggestions'),
                'topicKeywordsFound': analysis.get('topicKeywordsFound'),
                'bestMatchingSlide': analysis.get('bestMatchingSlide'),
                'expectedSlideNumber': analysis.get('expectedSlideNumber'),
                'timingDeviation': analysis.get('timingDeviation')
            })
        
        # Step 6: Save AIReport to database
        if effective_report_id:
            try:
                overall_score_value = overall_scores.get('overallScore', 0) if overall_scores else 0

                self.database_service.save_ai_report(
                    presentation_id=presentation_id,
                    report_id=effective_report_id,
                    overall_score=overall_score_value,
                    criterion_scores=rubric_scores,
                    report_content=report_content,
                    report_status="completed",
                    generated_by_model=self.report_service.model_name if hasattr(self.report_service, 'model_name') else "report-worker-v1",
                    report_body=webhook_report_body if 'webhook_report_body' in dir() else None
                )

                logger.info(f"✅ AIReport saved: reportId={effective_report_id}")
            except Exception as e:
                logger.error(f"   - Failed to save AIReport: {e}")

        # Final report completion log
        logger.info(f"🎉 REPORT COMPLETED SUCCESSFULLY")
        logger.info(f"   📋 Presentation ID: {presentation_id}")
        logger.info(f"   📝 Job ID: {job_id}")
        logger.info(f"   📊 Report ID: {effective_report_id}")
        logger.info(f"   ⭐ Overall Score: {overall_scores.get('overallScore', 0):.2f}/1.00")
        logger.info(f"   📄 Segments Analyzed: {len(segment_analyses)}")
        logger.info(f"   🖼️  Slides: {len(presentation_data.slides)}")

        return {
            'segmentAnalyses': segment_analyses_api,
            'overallScores': overall_scores or {},
            'rubricScores': rubric_scores,
            'reportBody': webhook_report_body if 'webhook_report_body' in dir() else {},
            'metadata': {
                'totalSegments': len(segment_analyses),
                'totalSlides': len(presentation_data.slides),
                'jobId': job_id,
                'reportId': effective_report_id,
                'classId': effective_class_id
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
