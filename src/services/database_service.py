"""
Database service for accessing and storing presentation analysis data
"""

import os
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
                host=os.getenv('DB_HOST', settings.DB_HOST),
                port=int(os.getenv('DB_PORT', '3306')),
                database=os.getenv('DB_DATABASE_NAME', settings.DB_NAME),
                user=os.getenv('DB_USERNAME', settings.DB_USER),
                password=os.getenv('DB_PASSWORD', settings.DB_PASSWORD),
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
                    t.topicName,
                    t.description as topicDescription
                FROM Presentations p
                JOIN Topics t ON p.topicId = t.topicId
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
                    configId,
                    analyzedAt,
                    processingTimeMs,
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
                    %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                analysis.segment_id,
                slide_id,
                datetime.now(),
                processing_time_ms,
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
                        configId = NULL,
                        overallScore = %s,
                        analyzedAt = %s,
                        processingTimeSeconds = %s,
                        aiModelVersion = %s,
                        status = 'done'
                    WHERE presentationId = %s
                """, (
                    overall_scores.overall_score,
                    datetime.now(),
                    processing_time_seconds,
                    ai_model_version,
                    presentation_id
                ))
                result_id = existing[0]
                logger.info(f"Updated AnalysisResults for presentationId={presentation_id}, resultId={result_id}")
            else:
                # Insert new record
                cursor.execute("""
                    INSERT INTO AnalysisResults (
                        presentationId,
                        configId,
                        overallScore,
                        analyzedAt,
                        processingTimeSeconds,
                        aiModelVersion,
                        status
                    ) VALUES (
                        %s, NULL, %s, %s, %s, %s, 'done'
                    )
                """, (
                    presentation_id,
                    overall_scores.overall_score,
                    datetime.now(),
                    processing_time_seconds,
                    ai_model_version
                ))
                
                result_id = cursor.lastrowid
                logger.info(f"Created AnalysisResults for presentationId={presentation_id}, resultId={result_id}")
            
            cursor.close()
            return result_id
            
        except MySQLError as e:
            raise DatabaseError(f"Failed to save analysis results: {e}")
    
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
    
    def close(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("Database connection closed")


# Singleton instance
_database_service = None

def get_database_service() -> DatabaseService:
    """Get database service singleton"""
    global _database_service
    if _database_service is None:
        _database_service = DatabaseService()
    return _database_service
