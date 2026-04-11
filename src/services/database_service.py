"""
Database service for accessing and storing presentation analysis data
"""

import json
import mysql.connector
from mysql.connector import Error as MySQLError
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime

from src.config.settings import settings
from src.utils.logger import get_logger
from src.utils.exceptions import DatabaseError

logger = get_logger(__name__)

@dataclass
class PresentationData:
    """Presentation data structure"""
    presentation_id: int
    title: str
    description: Optional[str]
    topic_id: int
    topic_name: str
    topic_description: Optional[str]
    transcript_segments: List[Dict[str, Any]]
    slides: List[Dict[str, Any]]
    job_id: Optional[int] = None
    class_id: Optional[int] = None
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    course_description: Optional[str] = None
    topic_requirements: Optional[str] = None

@dataclass
class SegmentAnalysisResult:
    """Segment analysis result structure"""
    segment_id: int
    relevance_score: float
    semantic_score: float
    alignment_score: float
    best_matching_slide: int
    expected_slide_number: int
    timing_deviation: float
    issues: List[str]
    suggestions: List[str]
    topic_keywords_found: List[str]
    processing_time_ms: Optional[int] = None

@dataclass
class OverallScores:
    """Overall scores structure"""
    content_relevance: float
    semantic_similarity: float
    slide_alignment: float
    overall_score: float
    processing_time_seconds: Optional[float] = None
    ai_model_version: str = "report-worker-v1"


class DatabaseService:
    """Service for database operations"""
    
    def __init__(self):
        self.connection = None
        self._connect()
    
    def _connect(self):
        """Connect to MySQL database"""
        try:
            self.connection = mysql.connector.connect(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                database=settings.DB_NAME,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                ssl_disabled=not settings.DB_SSL,
                autocommit=True
            )
            
            logger.info("✅ Connected to MySQL database")
            
        except MySQLError as e:
            raise DatabaseError(f"Failed to connect to database: {e}")
    
    def _ensure_connection(self):
        """Ensure database connection is active"""
        try:
            if not self.connection.is_connected():
                logger.warning("Database connection closed, reconnecting...")
                self._connect()
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            self._connect()
    
    def get_presentation_data(self, presentation_id: int) -> Optional[PresentationData]:
        """
        Get comprehensive presentation data for analysis
        
        Args:
            presentation_id: Presentation ID
            
        Returns:
            PresentationData object or None if not found
        """
        self._ensure_connection()
        
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            # Get presentation with topic information
            cursor.execute("""
                SELECT 
                    p.presentationId,
                    p.title,
                    p.description,
                    p.topicId,
                    p.classId,
                    t.topicName,
                    t.description as topicDescription,
                    t.requirements as topicRequirements,
                    c.courseId,
                    c.courseName,
                    c.description as courseDescription
                FROM Presentations p
                JOIN Topics t ON p.topicId = t.topicId
                JOIN Courses c ON t.courseId = c.courseId
                WHERE p.presentationId = %s
            """, (presentation_id,))
            
            presentation_row = cursor.fetchone()
            if not presentation_row:
                logger.warning(f"Presentation {presentation_id} not found")
                cursor.close()
                return None
            
            # Get job_id for this presentation
            cursor.execute("""
                SELECT jobId FROM Jobs 
                WHERE presentationId = %s 
                ORDER BY createdAt DESC LIMIT 1
            """, (presentation_id,))
            job_row = cursor.fetchone()
            job_id = job_row['jobId'] if job_row else None
            
            # Get transcript segments
            cursor.execute("""
                SELECT 
                    ts.segmentId,
                    ts.segmentNumber,
                    ts.startTimestamp,
                    ts.endTimestamp,
                    ts.segmentText,
                    ts.confidenceScore,
                    s.aiSpeakerLabel as speakerName
                FROM TranscriptSegments ts
                JOIN Transcripts t ON ts.transcriptId = t.transcriptId
                LEFT JOIN Speakers s ON ts.speakerId = s.speakerId
                WHERE t.presentationId = %s
                ORDER BY ts.segmentNumber ASC
            """, (presentation_id,))
            
            transcript_segments = cursor.fetchall()
            
            # Get slides with extracted text
            cursor.execute("""
                SELECT 
                    slideId,
                    slideNumber,
                    fileName,
                    filePath,
                    extractedText
                FROM Slides
                WHERE presentationId = %s
                ORDER BY slideNumber ASC
            """, (presentation_id,))
            
            slides = cursor.fetchall()
            cursor.close()
            
            return PresentationData(
                presentation_id=presentation_row['presentationId'],
                title=presentation_row['title'],
                description=presentation_row['description'],
                topic_id=presentation_row['topicId'],
                topic_name=presentation_row['topicName'],
                topic_description=presentation_row['topicDescription'],
                topic_requirements=presentation_row.get('topicRequirements'),
                class_id=presentation_row.get('classId'),
                course_id=presentation_row.get('courseId'),
                course_name=presentation_row.get('courseName'),
                course_description=presentation_row.get('courseDescription'),
                transcript_segments=transcript_segments,
                slides=slides,
                job_id=job_id
            )
                
        except MySQLError as e:
            raise DatabaseError(f"Database query error: {e}")
        except Exception as e:
            raise DatabaseError(f"Unexpected database error: {e}")
    
    def save_segment_analysis(self, analysis: SegmentAnalysisResult, slide_id: Optional[int] = None, processing_time_ms: Optional[int] = None) -> int:
        """
        Save segment analysis result to database
        
        Args:
            analysis: SegmentAnalysisResult object
            slide_id: Optional slide ID from best matching slide
            processing_time_ms: Processing time in milliseconds
            
        Returns:
            segAnalysisId of inserted record
        """
        self._ensure_connection()
        
        try:
            cursor = self.connection.cursor()
            
            cursor.execute("""
                INSERT INTO SegmentAnalyses (
                    segmentId,
                    slideId,
                    analyzedAt,
                    relevanceScore,
                    semanticScore,
                    alignmentScore,
                    bestMatchingSlide,
                    expectedSlideNumber,
                    timingDeviation,
                    issues,
                    suggestions,
                    topicKeywordsFound
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                analysis.segment_id,
                slide_id,
                datetime.now(),
                analysis.relevance_score,
                analysis.semantic_score,
                analysis.alignment_score,
                analysis.best_matching_slide,
                analysis.expected_slide_number,
                analysis.timing_deviation,
                json.dumps(analysis.issues, ensure_ascii=False),
                json.dumps(analysis.suggestions, ensure_ascii=False),
                json.dumps(analysis.topic_keywords_found, ensure_ascii=False)
            ))
            
            seg_analysis_id = cursor.lastrowid
            cursor.close()
            
            logger.debug(f"Saved segment analysis: segmentId={analysis.segment_id}, segAnalysisId={seg_analysis_id}")
            return seg_analysis_id
            
        except MySQLError as e:
            raise DatabaseError(f"Failed to save segment analysis: {e}")
    
    def save_analysis_results(self, presentation_id: int, overall_scores: OverallScores, processing_time_seconds: Optional[float] = None, ai_model_version: str = "report-worker-v1") -> int:
        """
        Save overall analysis results to database
        
        Args:
            presentation_id: Presentation ID
            overall_scores: OverallScores object
            processing_time_seconds: Total processing time in seconds
            ai_model_version: AI model version
            
        Returns:
            resultId of inserted record
        """
        self._ensure_connection()
        
        try:
            cursor = self.connection.cursor()
            
            # Check if AnalysisResults already exists for this presentation
            cursor.execute("""
                SELECT resultId FROM AnalysisResults 
                WHERE presentationId = %s
            """, (presentation_id,))
            
            existing = cursor.fetchone()
            
            if existing:
                # Update existing record
                cursor.execute("""
                    UPDATE AnalysisResults SET
                        overallScore = %s,
                        analyzedAt = %s,
                        status = 'done'
                    WHERE presentationId = %s
                """, (
                    overall_scores.overall_score,
                    datetime.now(),
                    presentation_id
                ))
                result_id = existing[0]
                logger.info(f"Updated AnalysisResults for presentationId={presentation_id}, resultId={result_id}")
            else:
                # Insert new record
                cursor.execute("""
                    INSERT INTO AnalysisResults (
                        presentationId,
                        overallScore,
                        analyzedAt,
                        status
                    ) VALUES (
                        %s, %s, %s, 'done'
                    )
                """, (
                    presentation_id,
                    overall_scores.overall_score,
                    datetime.now()
                ))
                
                result_id = cursor.lastrowid
                logger.info(f"Created AnalysisResults for presentationId={presentation_id}, resultId={result_id}")
            
            cursor.close()
            return result_id
            
        except MySQLError as e:
            raise DatabaseError(f"Failed to save analysis results: {e}")
    
    def get_analysis_results(self, presentation_id: int) -> Optional[Dict[str, Any]]:
        """
        Get overall analysis results for a presentation including all related quality metrics
        
        Args:
            presentation_id: Presentation ID
            
        Returns:
            Dict with analysis results and related quality metrics or None if not found
        """
        self._ensure_connection()
        
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            # Get AnalysisResults
            cursor.execute("""
                SELECT 
                    resultId,
                    presentationId,
                    overallScore,
                    analyzedAt,
                    status
                FROM AnalysisResults 
                WHERE presentationId = %s
            """, (presentation_id,))
            
            result = cursor.fetchone()
            
            if not result:
                cursor.close()
                return None
            
            result_id = result.get('resultId')
            
            # Get ContentQuality
            cursor.execute("""
                SELECT coherenceScore, depthScore, accuracyScore, topicCoverageScore, strengths, weaknesses
                FROM ContentQuality WHERE resultId = %s
            """, (result_id,))
            content_quality = cursor.fetchone()
            
            # Get DeliveryQuality
            cursor.execute("""
                SELECT clarityScore, pronunciationScore, volumeConsistency, speechRateWpm, voiceQuality
                FROM DeliveryQuality WHERE resultId = %s
            """, (result_id,))
            delivery_quality = cursor.fetchone()
            
            # Get StructureQuality
            cursor.execute("""
                SELECT organizationScore, transitionQuality, introConclusionScore, logicalFlowScore, structureNotes
                FROM StructureQuality WHERE resultId = %s
            """, (result_id,))
            structure_quality = cursor.fetchone()
            
            # Get EngagementMetric
            cursor.execute("""
                SELECT enthusiasmScore, variationScore, rhetoricalDeviceCount, emotionalTone
                FROM EngagementMetrics WHERE resultId = %s
            """, (result_id,))
            engagement_metric = cursor.fetchone()
            
            # Get SpeechPattern
            cursor.execute("""
                SELECT fillerWordCount, avgPauseDuration, longPauseCount, paceConsistency, fillerWordList
                FROM SpeechPatterns WHERE resultId = %s
            """, (result_id,))
            speech_pattern = cursor.fetchone()
            
            cursor.close()
            
            # Combine all data
            result['contentQuality'] = content_quality
            result['deliveryQuality'] = delivery_quality
            result['structureQuality'] = structure_quality
            result['engagementMetric'] = engagement_metric
            result['speechPattern'] = speech_pattern
            
            return result
            
        except MySQLError as e:
            raise DatabaseError(f"Failed to get analysis results: {e}")
    
    def check_presentation_exists(self, presentation_id: int) -> bool:
        """Check if presentation exists"""
        self._ensure_connection()
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                'SELECT 1 FROM Presentations WHERE presentationId = %s',
                (presentation_id,)
            )
            result = cursor.fetchone() is not None
            cursor.close()
            return result
                
        except MySQLError as e:
            raise DatabaseError(f"Database query error: {e}")
    
    def get_segment_analyses_count(self, presentation_id: int) -> int:
        """Get number of segment analyses for presentation"""
        self._ensure_connection()
        
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT COUNT(sa.segAnalysisId)
                FROM SegmentAnalyses sa
                JOIN TranscriptSegments ts ON sa.segmentId = ts.segmentId
                JOIN Transcripts t ON ts.transcriptId = t.transcriptId
                WHERE t.presentationId = %s
            """, (presentation_id,))
            
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else 0
                
        except MySQLError as e:
            raise DatabaseError(f"Database query error: {e}")
    
    def save_feedback(
        self,
        presentation_id: int,
        rating: float,
        comments: str,
        feedback_type: str = "general",
        reviewer_id: Optional[int] = None,
        is_visible_to_student: bool = True
    ) -> int:
        """
        Save feedback to Feedback table

        Args:
            presentation_id: Presentation ID
            rating: Rating (0-1 for AI, 1-5 for human)
            comments: Feedback comments text
            feedback_type: Type of feedback (general, content, delivery, structure, engagement)
            reviewer_id: ID of reviewer (null for AI)
            is_visible_to_student: Whether student can see this feedback

        Returns:
            feedbackId of inserted record
        """
        self._ensure_connection()

        # Map ai_report to general (since feedbackType is ENUM)
        if feedback_type == "ai_report":
            feedback_type = "general"
        
        # Map teamwork to general if not supported by DB ENUM
        # (will be stored as general but can be filtered in queries)
        if feedback_type == "teamwork":
            # Check if 'teamwork' is supported, fallback to 'general'
            try:
                cursor = self.connection.cursor()
                cursor.execute("SHOW COLUMNS FROM Feedback LIKE 'feedbackType'")
                result = cursor.fetchone()
                cursor.close()
                if result and 'teamwork' not in str(result):
                    feedback_type = "general"
            except:
                feedback_type = "general"

        # If no reviewer_id (AI), use 24 as placeholder since reviewerId is NOT NULL
        # (userId 24 is used as system/AI placeholder)
        if reviewer_id is None:
            reviewer_id = 24  # System/AI placeholder user

        try:
            cursor = self.connection.cursor()

            # Check if feedback already exists for this presentation and type
            cursor.execute("""
                SELECT feedbackId FROM Feedback
                WHERE presentationId = %s AND feedbackType = %s
            """, (presentation_id, feedback_type))

            existing = cursor.fetchone()

            if existing:
                # Update existing feedback
                cursor.execute("""
                    UPDATE Feedback SET
                        reviewerId = %s,
                        rating = %s,
                        comments = %s,
                        isVisibleToStudent = %s,
                        createdAtFeedback = NOW()
                    WHERE presentationId = %s AND feedbackType = %s
                """, (
                    reviewer_id,
                    rating,
                    comments,
                    1 if is_visible_to_student else 0,
                    presentation_id,
                    feedback_type
                ))
                feedback_id = existing[0]
                logger.info(f"Updated Feedback for presentationId={presentation_id}, feedbackId={feedback_id}")
            else:
                # Insert new feedback
                cursor.execute("""
                    INSERT INTO Feedback (
                        presentationId,
                        reviewerId,
                        rating,
                        comments,
                        feedbackType,
                        isVisibleToStudent,
                        createdAtFeedback
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (
                    presentation_id,
                    reviewer_id,
                    rating,
                    comments,
                    feedback_type,
                    1 if is_visible_to_student else 0
                ))

                feedback_id = cursor.lastrowid
                logger.info(f"Created Feedback for presentationId={presentation_id}, feedbackId={feedback_id}")

            cursor.close()
            return feedback_id

        except MySQLError as e:
            raise DatabaseError(f"Failed to save feedback: {e}")

    def get_segment_analyses_for_feedback(self, presentation_id: int) -> Dict[str, Any]:
        """
        Get segment analyses and overall scores for generating feedback

        Args:
            presentation_id: Presentation ID

        Returns:
            Dict with segment_analyses and overall_scores
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            # Get segment analyses
            cursor.execute("""
                SELECT
                    sa.segmentId,
                    sa.relevanceScore,
                    sa.semanticScore,
                    sa.alignmentScore,
                    sa.bestMatchingSlide,
                    sa.expectedSlideNumber,
                    sa.timingDeviation,
                    sa.issues,
                    sa.suggestions,
                    sa.topicKeywordsFound,
                    ts.segmentText,
                    ts.startTimestamp,
                    ts.endTimestamp
                FROM SegmentAnalyses sa
                JOIN TranscriptSegments ts ON sa.segmentId = ts.segmentId
                JOIN Transcripts t ON ts.transcriptId = t.transcriptId
                WHERE t.presentationId = %s
                ORDER BY ts.segmentNumber ASC
            """, (presentation_id,))

            segment_analyses = cursor.fetchall()

            # Calculate overall scores from segment analyses
            if segment_analyses:
                total = len(segment_analyses)
                avg_relevance = sum(float(sa.get('relevanceScore', 0) or 0) for sa in segment_analyses) / total
                avg_semantic = sum(float(sa.get('semanticScore', 0) or 0) for sa in segment_analyses) / total
                avg_alignment = sum(float(sa.get('alignmentScore', 0) or 0) for sa in segment_analyses) / total

                overall_scores = {
                    'overallScore': (avg_relevance * 0.3 + avg_semantic * 0.3 + avg_alignment * 0.4),
                    'contentRelevance': avg_relevance,
                    'semanticSimilarity': avg_semantic,
                    'slideAlignment': avg_alignment
                }
            else:
                overall_scores = None

            # Get presentation info
            cursor.execute("""
                SELECT
                    p.title,
                    t.topicName,
                    t.description as topicDescription
                FROM Presentations p
                JOIN Topics t ON p.topicId = t.topicId
                WHERE p.presentationId = %s
            """, (presentation_id,))

            presentation_info = cursor.fetchone()

            cursor.close()

            return {
                "segment_analyses": segment_analyses or [],
                "overall_scores": overall_scores,
                "presentation_info": presentation_info
            }

        except MySQLError as e:
            raise DatabaseError(f"Failed to get segment analyses for feedback: {e}")

    def get_transcript_with_speakers(self, presentation_id: int) -> Dict[str, Any]:
        """
        Get transcript segments with speaker information for teamwork analysis

        Args:
            presentation_id: Presentation ID

        Returns:
            Dict with segments, speakers, and analysis data
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            # Get transcript segments with speaker info
            cursor.execute("""
                SELECT
                    ts.segmentId,
                    ts.segmentNumber,
                    ts.startTimestamp,
                    ts.endTimestamp,
                    ts.segmentText,
                    ts.wordCount,
                    s.speakerId,
                    s.aiSpeakerLabel as speakerName
                FROM TranscriptSegments ts
                JOIN Transcripts t ON ts.transcriptId = t.transcriptId
                LEFT JOIN Speakers s ON ts.speakerId = s.speakerId
                WHERE t.presentationId = %s
                ORDER BY ts.segmentNumber ASC
            """, (presentation_id,))

            segments = cursor.fetchall()

            # Get unique speakers
            cursor.execute("""
                SELECT DISTINCT
                    s.speakerId,
                    s.aiSpeakerLabel as speakerName
                FROM TranscriptSegments ts
                JOIN Transcripts t ON ts.transcriptId = t.transcriptId
                LEFT JOIN Speakers s ON ts.speakerId = s.speakerId
                WHERE t.presentationId = %s AND s.speakerId IS NOT NULL
            """, (presentation_id,))

            speakers = cursor.fetchall()

            cursor.close()

            return {
                "segments": segments or [],
                "speakers": speakers or [],
                "segment_count": len(segments)
            }

        except MySQLError as e:
            raise DatabaseError(f"Failed to get transcript with speakers: {e}")

    def close(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("Database connection closed")

    # ============================================================
    # RUBRIC DATA METHODS
    # ============================================================

    def get_class_rubric_criteria(self, class_id: int) -> List[Dict[str, Any]]:
        """
        Get active rubric criteria for a class

        Args:
            class_id: Class ID

        Returns:
            List of rubric criteria
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            cursor.execute("""
                SELECT
                    classRubricCriteriaId,
                    classId,
                    rubricTemplateId,
                    criteriaName,
                    criteriaDescription,
                    weight,
                    maxScore,
                    displayOrder,
                    evaluationGuide
                FROM ClassRubricCriteria
                WHERE classId = %s AND isActive = 1
                ORDER BY displayOrder ASC
            """, (class_id,))

            criteria = cursor.fetchall()
            cursor.close()

            for row in criteria or []:
                if row.get("criteriaId") is None and row.get("classRubricCriteriaId") is not None:
                    row["criteriaId"] = row["classRubricCriteriaId"]

            logger.debug(f"Retrieved {len(criteria)} rubric criteria for class {class_id}")
            return criteria

        except MySQLError as e:
            raise DatabaseError(f"Failed to get rubric criteria: {e}")

    # ============================================================
    # SPEECH QUALITY DATA METHODS
    # ============================================================

    def get_speech_quality_analysis(self, presentation_id: int) -> Optional[Dict[str, Any]]:
        """
        Get speech quality analysis for a presentation

        Args:
            presentation_id: Presentation ID

        Returns:
            Dict with speech quality data or None
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            cursor.execute("""
                SELECT
                    id as analysisId,
                    presentationId,
                    jobId,
                    fluencyScore,
                    clarityScore,
                    confidenceScore,
                    overallScore,
                    totalHesitationCount,
                    totalHesitationTime,
                    hesitationRate,
                    speakingRate,
                    speechRhythmScore,
                    silenceRatio,
                    pitchVariation,
                    volumeVariation,
                    audioDuration,
                    pitchMean,
                    pitchStd,
                    energyMean,
                    energyStd,
                    voicedRatio,
                    createdAt
                FROM SpeechQualityAnalyses
                WHERE presentationId = %s
                ORDER BY createdAt DESC
                LIMIT 1
            """, (presentation_id,))

            result = cursor.fetchone()
            cursor.close()

            return result

        except MySQLError as e:
            logger.warning(f"Failed to get speech quality analysis: {e}")
            return None

    def get_hesitation_patterns(self, presentation_id: int) -> List[Dict[str, Any]]:
        """
        Get hesitation patterns for a presentation

        Args:
            presentation_id: Presentation ID

        Returns:
            List of hesitation patterns
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            cursor.execute("""
                SELECT
                    hp.id as patternId,
                    hp.speechAnalysisId,
                    hp.segmentId,
                    hp.startTime,
                    hp.endTime,
                    hp.duration,
                    hp.patternType,
                    hp.confidence
                FROM HesitationPatterns hp
                JOIN SpeechQualityAnalyses sq ON hp.speechAnalysisId = sq.id
                WHERE sq.presentationId = %s
                ORDER BY hp.startTime ASC
            """, (presentation_id,))

            patterns = cursor.fetchall()
            cursor.close()

            return patterns

        except MySQLError as e:
            logger.warning(f"Failed to get hesitation patterns: {e}")
            return []

    def get_segment_speech_quality(self, presentation_id: int) -> List[Dict[str, Any]]:
        """
        Get speech quality for each segment

        Args:
            presentation_id: Presentation ID

        Returns:
            List of segment speech quality data
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            cursor.execute("""
                SELECT
                    ssa.id as segmentSpeechQualityId,
                    ssa.segmentId,
                    ssa.segmentFluency as fluencyScore,
                    ssa.segmentClarity as clarityScore,
                    ssa.segmentConfidence as confidenceScore,
                    ssa.segmentHesitationCount as hesitationCount,
                    ssa.segmentSpeakingRate as speakingRate,
                    ssa.segmentStartTime as startTimestamp,
                    ssa.segmentEndTime as endTimestamp
                FROM SegmentSpeechQuality ssa
                JOIN SpeechQualityAnalyses sq ON ssa.speechAnalysisId = sq.id
                JOIN TranscriptSegments ts ON ssa.segmentId = ts.segmentId
                JOIN Transcripts t ON ts.transcriptId = t.transcriptId
                WHERE t.presentationId = %s
                ORDER BY ts.segmentNumber ASC
            """, (presentation_id,))

            results = cursor.fetchall()
            cursor.close()

            return results

        except MySQLError as e:
            logger.warning(f"Failed to get segment speech quality: {e}")
            return []

    # ============================================================
    # AI REPORT METHODS
    # ============================================================

    def save_ai_report(
        self,
        presentation_id: int,
        report_id: int,
        overall_score: float,
        criterion_scores: Dict[str, Any],
        report_content: str,
        report_status: str = "completed",
        generated_by_model: str = "report-worker-v1",
        report_body: Dict[str, Any] = None
    ) -> bool:
        """
        Save AI report to database

        Args:
            presentation_id: Presentation ID
            report_id: Report ID from AIReports table
            overall_score: Overall score (0-1)
            criterion_scores: Scores for each criterion (JSON)
            report_content: Generated report content
            report_status: Report status
            generated_by_model: AI model used
            report_body: Structured report body (summary, strengths, weaknesses, suggestions)

        Returns:
            True if successful
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor()

            # Check if reportBody column exists
            cursor.execute("SHOW COLUMNS FROM AIReports LIKE 'reportBody'")
            has_report_body_col = cursor.fetchone() is not None

            if has_report_body_col and report_body:
                cursor.execute("""
                    UPDATE AIReports SET
                        overallScore = %s,
                        criterionScores = %s,
                        reportContent = %s,
                        reportStatus = %s,
                        generatedByModel = %s,
                        generatedAt = %s,
                        reportBody = %s
                    WHERE reportId = %s
                """, (
                    overall_score,
                    json.dumps(criterion_scores, ensure_ascii=False),
                    report_content,
                    report_status,
                    generated_by_model,
                    datetime.now(),
                    json.dumps(report_body, ensure_ascii=False),
                    report_id
                ))
            else:
                cursor.execute("""
                    UPDATE AIReports SET
                        overallScore = %s,
                        criterionScores = %s,
                        reportContent = %s,
                        reportStatus = %s,
                        generatedByModel = %s,
                        generatedAt = %s
                    WHERE reportId = %s
                """, (
                    overall_score,
                    json.dumps(criterion_scores, ensure_ascii=False),
                    report_content,
                    report_status,
                    generated_by_model,
                    datetime.now(),
                    report_id
                ))

            cursor.close()
            logger.info(f"Updated AIReport {report_id} for presentation {presentation_id}")
            return True

        except MySQLError as e:
            raise DatabaseError(f"Failed to save AI report: {e}")

    def get_ai_report(self, presentation_id: int) -> Optional[Dict[str, Any]]:
        """
        Get AI report data by presentation ID (submission)

        Args:
            presentation_id: Presentation/Submission ID

        Returns:
            Dict with AI report data or None if not found
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)

            # Get AIReport by presentationId (presentation)
            cursor.execute("""
                SELECT
                    reportId,
                    presentationId,
                    classId,
                    overallScore,
                    criterionScores,
                    reportContent,
                    reportStatus,
                    generatedByModel,
                    generatedAt
                FROM AIReports
                WHERE presentationId = %s
                ORDER BY generatedAt DESC
                LIMIT 1
            """, (presentation_id,))

            result = cursor.fetchone()
            cursor.close()

            if not result:
                logger.debug(f"No AIReport found for presentationId={presentation_id}")
                return None

            # Parse JSON fields
            if result.get('criterionScores'):
                try:
                    result['criterionScores'] = json.loads(result['criterionScores'])
                except (json.JSONDecodeError, TypeError):
                    pass

            return result

        except MySQLError as e:
            raise DatabaseError(f"Failed to get AI report: {e}")

    def get_report_id_by_submission(self, submission_id: int) -> Optional[int]:
        """
        Find reportId from AIReports by presentationId (presentation ID).
        AIReports has unique constraint on presentationId, so at most one record exists.

        Args:
            submission_id: Presentation/Submission ID

        Returns:
            reportId if found, None otherwise
        """
        self._ensure_connection()

        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT reportId FROM AIReports
                WHERE presentationId = %s
                LIMIT 1
            """, (submission_id,))
            result = cursor.fetchone()
            cursor.close()

            if result:
                logger.debug(f"Found reportId={result['reportId']} for presentationId={submission_id}")
                return result['reportId']

            logger.debug(f"No AIReport found for presentationId={submission_id}")
            return None

        except MySQLError as e:
            raise DatabaseError(f"Failed to get reportId: {e}")

    def get_active_class_ai_setting_fk(self, class_id: int) -> Optional[Dict[str, Any]]:
        """
        Load active ClassAISettings row for a class (FK fields for AIReports).

        Returns:
            dict with classAiSettingId, or None if not found
        """
        if not class_id:
            return None
        self._ensure_connection()
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT classAiSettingId
                FROM ClassAISettings
                WHERE classId = %s AND isActive = 1
                LIMIT 1
                """,
                (class_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            return row
        except MySQLError as e:
            logger.warning("Failed to load ClassAISettings for class_id=%s: %s", class_id, e)
            return None

    def backfill_ai_report_class_setting_fks(self, report_id: int, class_id: int) -> None:
        """
        If AIReports row was created without ClassAISettings FKs, fill them from the active setting.
        Only updates columns that are currently NULL (does not overwrite Node-populated values).
        """
        fk = self.get_active_class_ai_setting_fk(class_id)
        if not fk or not report_id:
            return
        self._ensure_connection()
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                UPDATE AIReports SET
                    classAiSettingId = COALESCE(classAiSettingId, %s)
                WHERE reportId = %s
                """,
                (
                    fk.get("classAiSettingId"),
                    report_id,
                ),
            )
            self.connection.commit()
            cursor.close()
        except MySQLError as e:
            logger.warning("Failed to backfill AIReports FKs for reportId=%s: %s", report_id, e)

    def ensure_ai_report_record(self, submission_id: int, class_id: int) -> int:
        """
        Ensure an AIReports record exists for the given submission.
        If no record exists, INSERT one. Returns the reportId.

        Args:
            submission_id: Presentation/Submission ID
            class_id: Class ID

        Returns:
            reportId of existing or newly created record
        """
        # Try to find existing record first
        existing = self.get_report_id_by_submission(submission_id)
        if existing:
            logger.debug(f"AIReports record already exists: reportId={existing}")
            return existing

        # Insert new record (align with Node API: link ClassAISettings when available)
        fk = self.get_active_class_ai_setting_fk(class_id) if class_id else None
        self._ensure_connection()
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO AIReports (
                    presentationId, classId, classAiSettingId,
                    reportStatus, createdAt, updatedAt
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    submission_id,
                    class_id,
                    fk.get("classAiSettingId") if fk else None,
                    "pending",
                    datetime.now(),
                    datetime.now(),
                ),
            )
            new_id = cursor.lastrowid
            self.connection.commit()
            cursor.close()
            logger.info(f"Created new AIReports record: reportId={new_id}, presentationId={submission_id}")
            return new_id

        except MySQLError as e:
            raise DatabaseError(f"Failed to create AIReports record: {e}")


# Singleton instance
_database_service = None

def get_database_service() -> DatabaseService:
    """Get database service singleton"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
    return _database_service
