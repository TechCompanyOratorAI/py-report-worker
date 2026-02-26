"""
Report Analysis Service - Core logic for analyzing presentation segments

This service analyzes each transcript segment against slides and topic,
calculating scores and generating issues/suggestions.
"""

import json
import re
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta

from src.config.settings import settings
from src.services.database_service import (
    DatabaseService, 
    PresentationData, 
    SegmentAnalysisResult, 
    OverallScores
)
from src.utils.logger import get_logger
from src.utils.exceptions import AnalysisError

logger = get_logger(__name__)


class ReportAnalysisService:
    """Service for analyzing presentation segments and generating reports"""
    
    def __init__(self, database_service: DatabaseService):
        self.db = database_service
        self.similarity_threshold = settings.SIMILARITY_THRESHOLD
        self.relevance_threshold = settings.RELEVANCE_THRESHOLD
        self.alignment_threshold = settings.ALIGNMENT_THRESHOLD
        
    def analyze_presentation(
        self, 
        presentation_data: PresentationData
    ) -> Tuple[List[SegmentAnalysisResult], OverallScores]:
        """
        Analyze all segments of a presentation
        
        Args:
            presentation_data: Presentation data with segments and slides
            
        Returns:
            Tuple of (list of segment analyses, overall scores)
        """
        logger.info(f"🔍 Starting analysis for presentation {presentation_data.presentation_id}")
        logger.info(f"   - Segments: {len(presentation_data.transcript_segments)}")
        logger.info(f"   - Slides: {len(presentation_data.slides)}")
        
        # Extract topic keywords
        topic_keywords = self._extract_topic_keywords(
            presentation_data.topic_name,
            presentation_data.topic_description
        )
        
        # Build slide content map
        slide_contents = self._build_slide_content_map(presentation_data.slides)
        
        # Calculate total duration for timing analysis
        total_duration = self._calculate_total_duration(presentation_data.transcript_segments)
        
        # Analyze each segment
        segment_analyses = []
        
        for segment in presentation_data.transcript_segments:
            try:
                analysis = self._analyze_segment(
                    segment=segment,
                    topic_keywords=topic_keywords,
                    slide_contents=slide_contents,
                    slides=presentation_data.slides,
                    total_duration=total_duration,
                    total_segments=len(presentation_data.transcript_segments)
                )
                segment_analyses.append(analysis)
                
            except Exception as e:
                logger.error(f"Error analyzing segment {segment.get('segmentId')}: {e}")
                # Create a default analysis for failed segments
                segment_analyses.append(SegmentAnalysisResult(
                    segment_id=segment.get('segmentId', 0),
                    relevance_score=0.0,
                    semantic_score=0.0,
                    alignment_score=0.0,
                    best_matching_slide=0,
                    expected_slide_number=0,
                    timing_deviation=0.0,
                    issues=["Analysis failed"],
                    suggestions=["Retry analysis"],
                    topic_keywords_found=[]
                ))
        
        # Calculate overall scores
        overall_scores = self._calculate_overall_scores(segment_analyses)
        
        logger.info(f"✅ Analysis complete:")
        logger.info(f"   - Content Relevance: {overall_scores.content_relevance:.2f}")
        logger.info(f"   - Semantic Similarity: {overall_scores.semantic_similarity:.2f}")
        logger.info(f"   - Slide Alignment: {overall_scores.slide_alignment:.2f}")
        logger.info(f"   - Overall Score: {overall_scores.overall_score:.2f}")
        
        return segment_analyses, overall_scores
    
    def _extract_topic_keywords(self, topic_name: str, topic_description: str) -> List[str]:
        """
        Extract keywords from topic name and description
        
        Args:
            topic_name: Topic name
            topic_description: Topic description
            
        Returns:
            List of keywords
        """
        keywords = []
        
        # Combine text
        text = f"{topic_name} {topic_description or ''}"
        
        # Extract words (Vietnamese and English support)
        words = re.findall(r'\b[\w]{3,}\b', text.lower())
        
        # Filter common words and short words
        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 
                     'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
                     'và', 'của', 'trong', 'được', 'với', 'cho', 'từ', 'là',
                     'này', 'đó', 'các', 'vietnam', 'presentation', 'slide'}
        
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        # Remove duplicates while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords[:20]  # Limit to top 20 keywords
    
    def _build_slide_content_map(self, slides: List[Dict]) -> Dict[int, str]:
        """Build a map of slide number to content"""
        content_map = {}
        for slide in slides:
            slide_num = slide.get('slideNumber', 0)
            extracted_text = slide.get('extractedText', '') or ''
            content_map[slide_num] = extracted_text.lower()
        return content_map
    
    def _calculate_total_duration(self, segments: List[Dict]) -> float:
        """Calculate total duration from segments"""
        if not segments:
            return 0.0
        
        max_end = 0
        for seg in segments:
            end_time = seg.get('endTimestamp', 0)
            if end_time and end_time > max_end:
                max_end = end_time
        
        return float(max_end)
    
    def _analyze_segment(
        self,
        segment: Dict[str, Any],
        topic_keywords: List[str],
        slide_contents: Dict[int, str],
        slides: List[Dict],
        total_duration: float,
        total_segments: int
    ) -> SegmentAnalysisResult:
        """
        Analyze a single transcript segment
        
        Args:
            segment: Transcript segment data
            topic_keywords: Topic keywords
            slide_contents: Map of slide number to content
            slides: List of slides
            total_duration: Total presentation duration
            total_segments: Total number of segments
            
        Returns:
            SegmentAnalysisResult
        """
        segment_id = segment.get('segmentId', 0)
        segment_text = (segment.get('segmentText', '') or '').lower()
        start_time = float(segment.get('startTimestamp', 0) or 0)
        end_time = float(segment.get('endTimestamp', 0) or 0)
        
        # Find topic keywords in segment
        keywords_found = []
        for keyword in topic_keywords:
            if keyword.lower() in segment_text:
                keywords_found.append(keyword)
        
        # Calculate relevance score (based on topic keyword coverage)
        relevance_score = len(keywords_found) / max(len(topic_keywords), 1) if topic_keywords else 0.5
        relevance_score = min(relevance_score * 2, 1.0)  # Scale up
        
        # Find best matching slide (semantic similarity)
        best_matching_slide = 0
        best_similarity = 0.0
        
        for slide_num, slide_content in slide_contents.items():
            if not slide_content:
                continue
            
            # Simple keyword-based similarity
            keywords_in_slide = sum(1 for kw in keywords_found if kw in slide_content)
            similarity = keywords_in_slide / max(len(keywords_found), 1) if keywords_found else 0
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_matching_slide = slide_num
        
        semantic_score = best_similarity
        
        # Calculate expected slide number based on timing
        expected_slide_number = 1
        if total_duration > 0 and slides:
            progress = start_time / total_duration
            expected_slide_number = int(progress * len(slides)) + 1
            expected_slide_number = min(expected_slide_number, len(slides))
        
        # Calculate timing deviation
        timing_deviation = abs(best_matching_slide - expected_slide_number)
        alignment_score = 1.0 - min(timing_deviation / max(len(slides), 1), 1.0)
        
        # Generate issues and suggestions
        issues = []
        suggestions = []
        
        if relevance_score < self.relevance_threshold:
            issues.append(f"Low content relevance ({relevance_score:.2f})")
            suggestions.append("Add more topic-relevant content to this segment")
        
        if semantic_score < self.similarity_threshold:
            issues.append(f"No matching slide content found")
            suggestions.append("Ensure segment content aligns with current slide")
        
        if timing_deviation > 2:
            issues.append(f"Slide timing mismatch (expected slide {expected_slide_number}, showing {best_matching_slide})")
            suggestions.append("Adjust slide timing to match narration")
        
        if not keywords_found:
            issues.append("No topic keywords found in segment")
            suggestions.append("Include more topic-related vocabulary")
        
        # Create result
        result = SegmentAnalysisResult(
            segment_id=segment_id,
            relevance_score=round(relevance_score, 3),
            semantic_score=round(semantic_score, 3),
            alignment_score=round(alignment_score, 3),
            best_matching_slide=best_matching_slide,
            expected_slide_number=expected_slide_number,
            timing_deviation=round(timing_deviation, 2),
            issues=issues,
            suggestions=suggestions if suggestions else ["Good segment alignment"],
            topic_keywords_found=keywords_found
        )
        
        return result
    
    def _calculate_overall_scores(
        self, 
        segment_analyses: List[SegmentAnalysisResult]
    ) -> OverallScores:
        """
        Calculate overall scores from all segment analyses
        
        Args:
            segment_analyses: List of segment analysis results
            
        Returns:
            OverallScores object
        """
        if not segment_analyses:
            return OverallScores(
                content_relevance=0.0,
                semantic_similarity=0.0,
                slide_alignment=0.0,
                overall_score=0.0
            )
        
        # Calculate averages
        n = len(segment_analyses)
        
        avg_relevance = sum(a.relevance_score for a in segment_analyses) / n
        avg_semantic = sum(a.semantic_score for a in segment_analyses) / n
        avg_alignment = sum(a.alignment_score for a in segment_analyses) / n
        
        # Weighted overall score
        overall_score = (
            avg_relevance * 0.3 +
            avg_semantic * 0.3 +
            avg_alignment * 0.4
        )
        
        return OverallScores(
            content_relevance=round(avg_relevance, 3),
            semantic_similarity=round(avg_semantic, 3),
            slide_alignment=round(avg_alignment, 3),
            overall_score=round(overall_score, 3)
        )


# Singleton instance
_report_analysis_service = None

def get_report_analysis_service(db_service: DatabaseService = None) -> ReportAnalysisService:
    """Get report analysis service singleton"""
    global _report_analysis_service
    if _report_analysis_service is None:
        if db_service is None:
            db_service = get_database_service()
        _report_analysis_service = ReportAnalysisService(db_service)
    return _report_analysis_service


# Import for get_database_service
from src.services.database_service import get_database_service
