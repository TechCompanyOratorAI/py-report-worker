"""
Report Analysis Service - Core logic for analyzing presentation segments

This service analyzes each transcript segment against slides and topic,
calculating scores and generating issues/suggestions using Gemini AI.
"""

import json
import re
import google.genai as genai
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
        
        # Initialize Gemini AI
        if not settings.GEMINI_API_KEY:
            raise AnalysisError("GEMINI_API_KEY is not configured")
        
        # Use new google.genai client
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.GEMINI_MODEL
        logger.info(f"✅ Gemini AI initialized with model: {settings.GEMINI_MODEL}")
        
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
        Analyze a single transcript segment using Gemini AI
        
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
        segment_text = segment.get('segmentText', '') or segment.get('content', '')
        start_time = float(segment.get('startTimestamp', 0) or 0)
        end_time = float(segment.get('endTimestamp', 0) or 0)
        
        # Find current slide (from segment data or calculate)
        current_slide_id = segment.get('slideId', 1)
        current_slide_content = slide_contents.get(current_slide_id, '')
        
        # Prepare prompt for Gemini
        prompt = f"""You are an expert presentation analyst. Analyze this transcript segment and return ONLY valid JSON (no markdown, no explanation).

Presentation Context:
- Topic Keywords: {', '.join(topic_keywords)}
- Total Duration: {total_duration:.2f} seconds
- Current Slide ID: {current_slide_id}
- Total Segments: {total_segments}

Segment Information:
- Segment ID: {segment_id}
- Start Time: {start_time:.2f}s
- End Time: {end_time:.2f}s
- Text: {segment_text}

Slide Content (ID {current_slide_id}):
{current_slide_content}

Instructions:
Analyze and return JSON with these exact fields:
{{
  "relevance_score": <0-100: how relevant segment is to topic>,
  "semantic_score": <0-100: semantic quality and clarity of the narration>,
  "alignment_score": <0-100: how well narration matches the current slide>,
  "best_matching_slide": <slide ID that best matches this segment>,
  "expected_slide_number": <expected slide number based on timing>,
  "timing_deviation": <seconds early/late compared to ideal timing>,
  "issues": [<array of issues found, empty if none>],
  "suggestions": [<array of suggestions for improvement, empty if none>],
  "topic_keywords_found": [<array of topic keywords found in this segment>]
}}

Return ONLY the JSON object. No markdown, no code blocks."""

        try:
            # Call Gemini API using new google.genai client
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            result_text = response.text.strip()
            
            # Clean up response (remove markdown if present)
            if result_text.startswith('```'):
                result_text = result_text.split('```')[1]
                if result_text.startswith('json'):
                    result_text = result_text[4:]
            result_text = result_text.strip().strip('`')
            
            # Parse JSON
            result = json.loads(result_text)
            
            # Map to SegmentAnalysisResult
            return SegmentAnalysisResult(
                segment_id=segment_id,
                relevance_score=result.get('relevance_score', 50) / 100.0,
                semantic_score=result.get('semantic_score', 50) / 100.0,
                alignment_score=result.get('alignment_score', 50) / 100.0,
                best_matching_slide=result.get('best_matching_slide', current_slide_id),
                expected_slide_number=result.get('expected_slide_number', 1),
                timing_deviation=float(result.get('timing_deviation', 0)),
                issues=result.get('issues', []),
                suggestions=result.get('suggestions', ['Good segment']),
                topic_keywords_found=result.get('topic_keywords_found', topic_keywords[:5])
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Gemini response: {e}, using fallback")
            return self._analyze_segment_fallback(segment, topic_keywords, slide_contents, slides, total_duration, total_segments, current_slide_id)
        except Exception as e:
            logger.warning(f"Gemini API error: {e}, using fallback")
            return self._analyze_segment_fallback(segment, topic_keywords, slide_contents, slides, total_duration, total_segments, current_slide_id)
    
    def _analyze_segment_fallback(
        self,
        segment: Dict[str, Any],
        topic_keywords: List[str],
        slide_contents: Dict[int, str],
        slides: List[Dict],
        total_duration: float,
        total_segments: int,
        current_slide_id: int
    ) -> SegmentAnalysisResult:
        """Fallback analysis using rule-based method if AI fails"""
        segment_id = segment.get('segmentId', 0)
        segment_text = (segment.get('segmentText', '') or '').lower()
        start_time = float(segment.get('startTimestamp', 0) or 0)
        
        # Find topic keywords in segment
        keywords_found = [kw for kw in topic_keywords if kw.lower() in segment_text]
        
        # Calculate relevance score
        relevance_score = len(keywords_found) / max(len(topic_keywords), 1) if topic_keywords else 0.5
        relevance_score = min(relevance_score * 2, 1.0)
        
        # Find best matching slide
        best_matching_slide = current_slide_id
        best_similarity = 0.0
        
        for slide_num, slide_content in slide_contents.items():
            if slide_content:
                keywords_in_slide = sum(1 for kw in keywords_found if kw in slide_content)
                similarity = keywords_in_slide / max(len(keywords_found), 1) if keywords_found else 0
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_matching_slide = slide_num
        
        semantic_score = best_similarity
        
        # Expected slide number
        expected_slide_number = 1
        if total_duration > 0 and slides:
            progress = start_time / total_duration
            expected_slide_number = int(progress * len(slides)) + 1
            expected_slide_number = min(expected_slide_number, len(slides))
        
        timing_deviation = abs(best_matching_slide - expected_slide_number)
        alignment_score = 1.0 - min(timing_deviation / max(len(slides), 1), 1.0)
        
        # Issues and suggestions
        issues = []
        suggestions = []
        
        if relevance_score < self.relevance_threshold:
            issues.append(f"Low content relevance ({relevance_score:.2f})")
            suggestions.append("Add more topic-relevant content")
        
        if semantic_score < self.similarity_threshold:
            issues.append("No matching slide content found")
            suggestions.append("Ensure segment content aligns with slide")
        
        if timing_deviation > 2:
            issues.append(f"Slide timing mismatch")
            suggestions.append("Adjust slide timing to match narration")
        
        if not keywords_found:
            issues.append("No topic keywords found")
            suggestions.append("Include more topic-related vocabulary")
        
        return SegmentAnalysisResult(
            segment_id=segment_id,
            relevance_score=round(relevance_score, 3),
            semantic_score=round(semantic_score, 3),
            alignment_score=round(alignment_score, 3),
            best_matching_slide=best_matching_slide,
            expected_slide_number=expected_slide_number,
            timing_deviation=round(timing_deviation, 2),
            issues=issues if issues else ["Good segment alignment"],
            suggestions=suggestions if suggestions else ["Continue with good practices"],
            topic_keywords_found=keywords_found
        )
    
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

    def generate_feedback(
        self,
        presentation_title: str,
        topic_name: str,
        topic_description: str,
        segment_analyses: List[Dict],
        overall_scores: Dict
    ) -> Dict[str, Any]:
        """
        Generate comprehensive feedback using Gemini AI

        Args:
            presentation_title: Title of presentation
            topic_name: Topic name
            topic_description: Topic description
            segment_analyses: List of segment analysis results from DB
            overall_scores: Overall scores from AnalysisResults

        Returns:
            Dict with rating (1-5) and comments
        """
        logger.info("🤖 Generating feedback with Gemini AI...")

        # Prepare summary data for prompt
        # Take up to 10 segments (5 best, 5 worst) to keep prompt manageable
        if len(segment_analyses) > 10:
            sorted_by_score = sorted(
                segment_analyses,
                key=lambda x: x.get('relevanceScore', 0) + x.get('semanticScore', 0) + x.get('alignmentScore', 0)
            )
            worst_segments = sorted_by_score[:5]
            best_segments = sorted_by_score[-5:]
            selected_segments = worst_segments + best_segments
        else:
            selected_segments = segment_analyses

        # Build segment summaries
        segments_summary = []
        for seg in selected_segments:
            issues = seg.get('issues', [])
            suggestions = seg.get('suggestions', [])
            if isinstance(issues, str):
                import json
                try:
                    issues = json.loads(issues)
                except:
                    issues = []
            if isinstance(suggestions, str):
                import json
                try:
                    suggestions = json.loads(suggestions)
                except:
                    suggestions = []

            segments_summary.append({
                'segment_id': seg.get('segmentId'),
                'relevance_score': seg.get('relevanceScore', 0),
                'semantic_score': seg.get('semanticScore', 0),
                'alignment_score': seg.get('alignmentScore', 0),
                'best_matching_slide': seg.get('bestMatchingSlide'),
                'timing_deviation': seg.get('timingDeviation', 0),
                'issues': issues[:3],  # Top 3 issues per segment
                'suggestions': suggestions[:3],  # Top 3 suggestions
                'segment_text': (seg.get('segmentText', '') or '')[:200]  # Truncate long text
            })

        # Count common issues and suggestions across all segments
        all_issues = []
        all_suggestions = []
        for seg in segment_analyses:
            issues = seg.get('issues', [])
            suggestions = seg.get('suggestions', [])
            if isinstance(issues, str):
                import json
                try:
                    issues = json.loads(issues)
                except:
                    issues = []
            if isinstance(suggestions, str):
                import json
                try:
                    suggestions = json.loads(suggestions)
                except:
                    suggestions = []
            all_issues.extend(issues)
            all_suggestions.extend(suggestions)

        # Get top issues and suggestions
        from collections import Counter
        top_issues = Counter(all_issues).most_common(5)
        top_suggestions = Counter(all_suggestions).most_common(5)

        prompt = f"""Bạn là một chuyên gia đánh giá bài thuyết trình. Hãy viết feedback tổng quan cho bài thuyết trình dựa trên dữ liệu phân tích dưới đây.

Thông tin bài thuyết trình:
- Tiêu đề: {presentation_title}
- Chủ đề: {topic_name}
- Mô tả chủ đề: {topic_description}

Điểm tổng quan:
- Overall Score: {overall_scores.get('overallScore', 0):.2f}/1.0
- Content Relevance: {overall_scores.get('contentRelevance', 0):.2f}/1.0
- Semantic Similarity: {overall_scores.get('semanticSimilarity', 0):.2f}/1.0
- Slide Alignment: {overall_scores.get('slideAlignment', 0):.2f}/1.0

Các vấn đề phổ biến nhất:
{chr(10).join([f"- {issue[0]}" for issue in top_issues])}

Các đề xuất cải thiện phổ biến nhất:
{chr(10).join([f"- {suggestion[0]}" for suggestion in top_suggestions])}

Chi tiết một số segment tiêu biểu:
{chr(10).join([
    f"Segment {seg['segment_id']}: relevance={seg['relevance_score']:.2f}, semantic={seg['semantic_score']:.2f}, alignment={seg['alignment_score']:.2f}, issues={seg['issues']}"
    for seg in segments_summary[:8]
])}

Hãy trả về JSON với các trường sau (KHÔNG có markdown, KHÔNG có giải thích):
{{
  "rating": <điểm đánh giá từ 1-5, dựa trên overallScore>,
  "comments": "<đoạn feedback tổng quan bằng tiếng Việt, viết theo phong cách constructive feedback, khoảng 300-500 từ, bao gồm: điểm mạnh, điểm cần cải thiện, và gợi ý cụ thể>
}}

Lưu ý:
- rating phải là số nguyên từ 1-5
- comments phải là text tiếng Việt, có cấu trúc rõ ràng
- Viết feedback mang tính xây dựng, khích lệ học viên
- Nếu overallScore > 0.7 thì rating nên là 4-5
- Nếu overallScore < 0.4 thì rating nên là 1-2

Return ONLY the JSON object. No markdown, no explanation."""

        try:
            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            result_text = response.text.strip()

            # Clean up response
            if result_text.startswith('```'):
                result_text = result_text.split('```')[1]
                if result_text.startswith('json'):
                    result_text = result_text[4:]
            result_text = result_text.strip().strip('`')

            # Parse JSON
            result = json.loads(result_text)

            rating = int(result.get('rating', 3))
            comments = str(result.get('comments', ''))

            # Clamp rating to 1-5
            rating = max(1, min(5, rating))

            logger.info(f"✅ Generated feedback: rating={rating}, comments_length={len(comments)}")

            return {
                'rating': rating,
                'overall_score': overall_scores.get('overallScore', 0),
                'comments': comments,
                'feedback_type': 'ai_report'
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Gemini feedback response: {e}")
            return self._generate_feedback_fallback(overall_scores, top_issues, top_suggestions)
        except Exception as e:
            logger.warning(f"Gemini API error generating feedback: {e}")
            return self._generate_feedback_fallback(overall_scores, top_issues, top_suggestions)

    def _generate_feedback_fallback(
        self,
        overall_scores: Dict,
        top_issues: list,
        top_suggestions: list
    ) -> Dict[str, Any]:
        """
        Generate basic feedback without AI if Gemini fails
        """
        overall_score = overall_scores.get('overallScore', 0)
        content_relevance = overall_scores.get('contentRelevance', 0)
        semantic_similarity = overall_scores.get('semanticSimilarity', 0)
        slide_alignment = overall_scores.get('slideAlignment', 0)

        # Calculate rating
        rating = round(overall_score * 5)
        rating = max(1, min(5, rating))

        # Build comments
        strengths = []
        weaknesses = []
        suggestions = []

        if content_relevance >= 0.7:
            strengths.append("Nội dung bài thuyết trình liên quan tốt đến chủ đề")
        elif content_relevance < 0.5:
            weaknesses.append("Nội dung cần tập trung hơn vào chủ đề chính")

        if semantic_similarity >= 0.7:
            strengths.append("Trình bày rõ ràng, mạch lạc")
        elif semantic_similarity < 0.5:
            weaknesses.append("Cần cải thiện cách diễn đạt để rõ ràng hơn")

        if slide_alignment >= 0.7:
            strengths.append("Căn chỉnh tốt giữa nói và slide")
        elif slide_alignment < 0.5:
            weaknesses.append("Cần cải thiện sự đồng bộ giữa nội dung nói và slide")

        # Add top suggestions
        for suggestion, _ in top_suggestions[:3]:
            suggestions.append(suggestion)

        # Build comments text
        comments_parts = []

        if strengths:
            comments_parts.append("**Điểm mạnh:**\n- " + "\n- ".join(strengths))

        if weaknesses:
            comments_parts.append("**Điểm cần cải thiện:**\n- " + "\n- ".join(weaknesses))

        if suggestions:
            comments_parts.append("**Gợi ý cải thiện:**\n- " + "\n- ".join(suggestions[:3]))

        comments_parts.append(f"\n\n**Điểm số tổng:** {overall_score:.2f}/1.0 ({rating}/5)")

        comments = "\n\n".join(comments_parts)

        return {
            'rating': rating,
            'overall_score': overall_score,
            'comments': comments,
            'feedback_type': 'ai_report'
        }


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

from src.services.database_service import get_database_service
