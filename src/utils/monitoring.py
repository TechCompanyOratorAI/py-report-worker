"""
Monitoring utilities for Report Worker
Reusable functions for database, queue, and progress queries
"""

import sys
sys.path.insert(0, 'src')

import mysql.connector
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from config.settings import settings


@dataclass
class QueueStatus:
    """SQS queue status"""
    messages_visible: int
    messages_processing: int
    total: int


@dataclass
class ProgressStatus:
    """Processing progress status"""
    segment_count: int
    total_segments: int
    percentage: float
    is_completed: bool
    latest_result: Optional[Dict[str, Any]]


@dataclass
class PresentationInfo:
    """Presentation information"""
    presentation_id: int
    title: str
    topic_name: str
    transcript_segments: int
    slides: int


def get_db_connection():
    """
    Create a simple database connection
    
    Returns:
        MySQL connection object
    """
    return mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        ssl_disabled=not settings.DB_SSL
    )


def get_queue_status() -> Optional[QueueStatus]:
    """
    Get SQS queue status
    
    Returns:
        QueueStatus object or None if error
    """
    try:
        from services.sqs_service import SQSService
        sqs = SQSService()
        response = sqs.client.get_queue_attributes(
            QueueUrl=sqs.queue_url,
            AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
        )
        attributes = response.get('Attributes', {})
        messages_visible = int(attributes.get('ApproximateNumberOfMessages', 0))
        messages_processing = int(attributes.get('ApproximateNumberOfMessagesNotVisible', 0))
        
        return QueueStatus(
            messages_visible=messages_visible,
            messages_processing=messages_processing,
            total=messages_visible + messages_processing
        )
    except Exception as e:
        print(f"Error getting queue status: {e}")
        return None


def get_progress_status(presentation_id: int = 13, total_segments: int = 223) -> Optional[ProgressStatus]:
    """
    Get processing progress for a presentation
    
    Args:
        presentation_id: Presentation ID to check
        total_segments: Total expected segments
        
    Returns:
        ProgressStatus object or None if error
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get segment count
        cursor.execute("SELECT COUNT(*) FROM SegmentAnalyses sa JOIN TranscriptSegments ts ON sa.segmentId = ts.segmentId JOIN Transcripts t ON ts.transcriptId = t.transcriptId WHERE t.presentationId = %s", (presentation_id,))
        seg_count = cursor.fetchone()[0]
        
        # Get latest result
        cursor.execute("""
            SELECT resultId, presentationId, overallScore, contentRelevance, semanticSimilarity, slideAlignment, analyzedAt
            FROM AnalysisResults 
            WHERE presentationId = %s 
            ORDER BY analyzedAt DESC 
            LIMIT 1
        """, (presentation_id,))
        result = cursor.fetchone()
        
        conn.close()
        
        is_completed = result is not None
        percentage = (seg_count / total_segments) * 100 if total_segments > 0 else 0
        
        latest_result = None
        if result:
            latest_result = {
                'result_id': result[0],
                'presentation_id': result[1],
                'overall_score': result[2],
                'content_relevance': result[3],
                'semantic_similarity': result[4],
                'slide_alignment': result[5],
                'analyzed_at': result[6]
            }
        
        return ProgressStatus(
            segment_count=seg_count,
            total_segments=total_segments,
            percentage=percentage,
            is_completed=is_completed,
            latest_result=latest_result
        )
    except Exception as e:
        print(f"Error getting progress status: {e}")
        return None


def check_presentation(presentation_id: int) -> Optional[PresentationInfo]:
    """
    Check if a presentation exists and get its info
    
    Args:
        presentation_id: Presentation ID to check
        
    Returns:
        PresentationInfo object or None if not found/error
    """
    try:
        from services.database_service import DatabaseService
        db = DatabaseService()
        pres_data = db.get_presentation_data(presentation_id)
        
        if not pres_data:
            return None
        
        return PresentationInfo(
            presentation_id=pres_data.presentation_id,
            title=pres_data.title,
            topic_name=pres_data.topic_name,
            transcript_segments=len(pres_data.transcript_segments),
            slides=len(pres_data.slides)
        )
    except Exception as e:
        print(f"Error checking presentation: {e}")
        return None


def get_analysis_results(presentation_id: Optional[int] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get analysis results from database
    
    Args:
        presentation_id: Optional presentation ID to filter
        limit: Number of results to return
        
    Returns:
        List of result dictionaries
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if presentation_id:
            cursor.execute("""
                SELECT 
                    ar.resultId,
                    ar.presentationId,
                    p.title,
                    ar.contentRelevance,
                    ar.semanticSimilarity,
                    ar.slideAlignment,
                    ar.overallScore,
                    ar.analyzedAt
                FROM AnalysisResults ar
                LEFT JOIN Presentations p ON ar.presentationId = p.presentationId
                WHERE ar.presentationId = %s
                ORDER BY ar.analyzedAt DESC
                LIMIT %s
            """, (presentation_id, limit))
        else:
            cursor.execute("""
                SELECT 
                    ar.resultId,
                    ar.presentationId,
                    p.title,
                    ar.contentRelevance,
                    ar.semanticSimilarity,
                    ar.slideAlignment,
                    ar.overallScore,
                    ar.analyzedAt
                FROM AnalysisResults ar
                LEFT JOIN Presentations p ON ar.presentationId = p.presentationId
                ORDER BY ar.analyzedAt DESC
                LIMIT %s
            """, (limit,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'result_id': row[0],
                'presentation_id': row[1],
                'title': row[2],
                'content_relevance': row[3],
                'semantic_similarity': row[4],
                'slide_alignment': row[5],
                'overall_score': row[6],
                'analyzed_at': row[7]
            })
        
        conn.close()
        return results
    except Exception as e:
        print(f"Error getting analysis results: {e}")
        return []


def get_segment_analyses_summary() -> List[Dict[str, Any]]:
    """
    Get segment analysis summary grouped by presentation
    
    Returns:
        List of summary dictionaries
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                sa.presentationId,
                COUNT(*) as segment_count,
                AVG(sa.relevanceScore) as avg_relevance,
                AVG(sa.semanticScore) as avg_semantic,
                AVG(sa.alignmentScore) as avg_alignment
            FROM SegmentAnalyses sa
            GROUP BY sa.presentationId
            ORDER BY sa.presentationId DESC
            LIMIT 10
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'presentation_id': row[0],
                'segment_count': row[1],
                'avg_relevance': row[2],
                'avg_semantic': row[3],
                'avg_alignment': row[4]
            })
        
        conn.close()
        return results
    except Exception as e:
        print(f"Error getting segment analyses summary: {e}")
        return []


def check_database_schema() -> Dict[str, List[str]]:
    """
    Check database schema for key tables
    
    Returns:
        Dictionary mapping table names to column lists
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        schema = {}
        for table in ['AnalysisResults', 'SegmentAnalyses', 'Presentations', 'Topics', 'Slides', 'TranscriptSegments']:
            try:
                cursor.execute(f"DESCRIBE {table}")
                columns = [row[0] for row in cursor.fetchall()]
                schema[table] = columns
            except:
                schema[table] = []
        
        conn.close()
        return schema
    except Exception as e:
        print(f"Error checking schema: {e}")
        return {}
