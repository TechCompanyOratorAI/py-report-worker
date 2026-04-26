"""
Report Analysis Service - Core logic for analyzing presentation segments

This service analyzes each transcript segment against slides and topic,
calculating scores and generating issues/suggestions using AI (OpenAI or Gemini).
"""

import json
import re
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

# Import AI clients
try:
    import google.genai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from src.config.settings import settings
from src.services.database_service import (
    DatabaseService, 
    PresentationData, 
    SegmentAnalysisResult, 
    OverallScores,
    get_database_service
)
from src.utils.logger import get_logger
from src.utils.exceptions import AnalysisError, QuotaExceededError

logger = get_logger(__name__)


class ReportAnalysisService:
    """Service for analyzing presentation segments and generating reports"""
    
    def __init__(self, database_service: DatabaseService):
        self.db = database_service
        self.similarity_threshold = settings.SIMILARITY_THRESHOLD
        self.relevance_threshold = settings.RELEVANCE_THRESHOLD
        self.alignment_threshold = settings.ALIGNMENT_THRESHOLD
        
        # Initialize AI client based on provider setting
        self.ai_provider = settings.AI_PROVIDER.lower()
        
        if self.ai_provider == 'openai':
            if not settings.OPENAI_API_KEY:
                raise AnalysisError("OPENAI_API_KEY is not configured")
            
            if not OPENAI_AVAILABLE:
                raise AnalysisError("openai package not installed")
            
            self.openai_client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL
            )
            self.model_name = settings.OPENAI_MODEL
            logger.info(f"✅ OpenAI AI initialized with model: {settings.OPENAI_MODEL}, base_url: {settings.OPENAI_BASE_URL}")
            
        elif self.ai_provider == 'gemini':
            if not settings.GEMINI_API_KEY:
                raise AnalysisError("GEMINI_API_KEY is not configured")
            
            if not GEMINI_AVAILABLE:
                raise AnalysisError("google-genai package not installed")
            
            self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            self.model_name = settings.GEMINI_MODEL
            logger.info(f"✅ Gemini AI initialized with model: {settings.GEMINI_MODEL}")
        else:
            raise AnalysisError(f"Invalid AI_PROVIDER: {self.ai_provider}. Use 'openai' or 'gemini'")
    
    def _call_ai(self, prompt: str) -> str:
        """Call AI API based on configured provider"""
        try:
            if self.ai_provider == 'openai':
                response = self.openai_client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=200
                )
                return response.choices[0].message.content
                
            elif self.ai_provider == 'gemini':
                response = self.gemini_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return response.text
                
        except Exception as e:
            err_str = str(e)
            is_quota = (
                "'code': 402" in err_str or
                err_str.startswith("Error code: 402") or
                (hasattr(e, 'status_code') and e.status_code == 402)
            )
            if is_quota:
                raise QuotaExceededError(str(e)) from e
            logger.error(f"AI API call failed: {e}")
            raise
        
    def analyze_presentation(
        self, 
        presentation_data: PresentationData
    ) -> Tuple[List[SegmentAnalysisResult], OverallScores]:
        """Analyze all segments of a presentation"""
        logger.info(f"🔍 Starting analysis for presentation {presentation_data.presentation_id}")
        logger.info(f"   - Segments: {len(presentation_data.transcript_segments)}")
        logger.info(f"   - Slides: {len(presentation_data.slides)}")
        
        topic_keywords = self._extract_topic_keywords(
            presentation_data.topic_name,
            presentation_data.topic_description
        )
        
        slide_contents = self._build_slide_content_map(presentation_data.slides)
        total_duration = self._calculate_total_duration(presentation_data.transcript_segments)
        
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
        
        overall_scores = self._calculate_overall_scores(segment_analyses)
        
        logger.info(f"✅ Analysis complete:")
        logger.info(f"   - Content Relevance: {overall_scores.content_relevance:.2f}")
        logger.info(f"   - Semantic Similarity: {overall_scores.semantic_similarity:.2f}")
        logger.info(f"   - Slide Alignment: {overall_scores.slide_alignment:.2f}")
        logger.info(f"   - Overall Score: {overall_scores.overall_score:.2f}")
        
        return segment_analyses, overall_scores
    
    def _extract_topic_keywords(self, topic_name: str, topic_description: str) -> List[str]:
        """Extract keywords from topic name and description"""
        keywords = []
        text = f"{topic_name} {topic_description or ''}"
        words = re.findall(r'\b[\w]{3,}\b', text.lower())
        
        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 
                     'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
                     'và', 'của', 'trong', 'được', 'với', 'cho', 'từ', 'là',
                     'này', 'đó', 'các', 'vietnam', 'presentation', 'slide'}
        
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords[:20]
    
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
        """Analyze a single transcript segment using AI"""
        segment_id = segment.get('segmentId', 0)
        segment_text = segment.get('segmentText', '') or segment.get('content', '')
        start_time = float(segment.get('startTimestamp', 0) or 0)
        end_time = float(segment.get('endTimestamp', 0) or 0)
        
        current_slide_id = segment.get('slideId', 1)
        current_slide_content = slide_contents.get(current_slide_id, '')
        
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
            result_text = self._call_ai(prompt)
            
            if result_text.startswith('```'):
                result_text = result_text.split('```')[1]
                if result_text.startswith('json'):
                    result_text = result_text[4:]
            result_text = result_text.strip().strip('`')
            
            result = json.loads(result_text)
            
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
                topic_keywords_found=result.get('topic_keywords_found', topic_keywords[:5]),
                speaker_label=segment.get('speakerName', None)
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI response: {e}, using fallback")
            return self._analyze_segment_fallback(segment, topic_keywords, slide_contents, slides, total_duration, total_segments, current_slide_id)
        except Exception as e:
            logger.warning(f"AI API error: {e}, using fallback")
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
        
        keywords_found = [kw for kw in topic_keywords if kw.lower() in segment_text]
        
        relevance_score = len(keywords_found) / max(len(topic_keywords), 1) if topic_keywords else 0.5
        relevance_score = min(relevance_score * 2, 1.0)
        
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
        
        expected_slide_number = 1
        if total_duration > 0 and slides:
            progress = start_time / total_duration
            expected_slide_number = int(progress * len(slides)) + 1
            expected_slide_number = min(expected_slide_number, len(slides))
        
        timing_deviation = abs(best_matching_slide - expected_slide_number)
        alignment_score = 1.0 - min(timing_deviation / max(len(slides), 1), 1.0)
        
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
            topic_keywords_found=keywords_found,
            speaker_label=segment.get('speakerName', None)
        )
    
    def _calculate_overall_scores(
        self,
        segment_analyses: List[SegmentAnalysisResult]
    ) -> OverallScores:
        """Calculate overall scores from all segment analyses"""
        if not segment_analyses:
            return OverallScores(
                content_relevance=0.0,
                semantic_similarity=0.0,
                slide_alignment=0.0,
                overall_score=0.0
            )

        n = len(segment_analyses)
        avg_relevance = sum(a.relevance_score for a in segment_analyses) / n
        avg_semantic = sum(a.semantic_score for a in segment_analyses) / n
        avg_alignment = sum(a.alignment_score for a in segment_analyses) / n

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
        overall_scores: Dict,
        course_name: str = None,
        course_description: str = None,
        topic_requirements: str = None
    ) -> Dict[str, Any]:
        """Generate comprehensive feedback using AI"""
        logger.info(f"🤖 Generating feedback with {self.ai_provider.upper()} AI...")

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

        all_issues = []
        all_suggestions = []
        speaker_issues = {}
        speaker_suggestions = {}
        for seg in segment_analyses:
            speaker = seg.get('speakerLabel') or seg.get('speakerName') or 'Không xác định'
            issues = seg.get('issues', [])
            suggestions = seg.get('suggestions', [])
            if isinstance(issues, str):
                try:
                    issues = json.loads(issues)
                except:
                    issues = []
            if isinstance(suggestions, str):
                try:
                    suggestions = json.loads(suggestions)
                except:
                    suggestions = []
            all_issues.extend(issues)
            all_suggestions.extend(suggestions)
            
            if speaker not in speaker_issues:
                speaker_issues[speaker] = []
                speaker_suggestions[speaker] = []
            speaker_issues[speaker].extend(issues)
            speaker_suggestions[speaker].extend(suggestions)

        from collections import Counter
        top_issues = Counter(all_issues).most_common(5)
        top_suggestions = Counter(all_suggestions).most_common(5)
        
        speaker_feedback_info = ""
        if len(speaker_issues) > 1 or (len(speaker_issues) == 1 and list(speaker_issues.keys())[0] != 'Không xác định'):
            speaker_feedback_info = "Chi tiết đánh giá theo từng người nói:"
            for speaker in speaker_issues.keys():
                top_spk_issues = Counter(speaker_issues[speaker]).most_common(3)
                top_spk_sugg = Counter(speaker_suggestions[speaker]).most_common(3)
                speaker_feedback_info += f"\n- {speaker}:"
                if top_spk_issues:
                    speaker_feedback_info += f"\n  + Vị trí chưa tốt chủ yếu: {', '.join([i[0] for i in top_spk_issues])}"
                if top_spk_sugg:
                    speaker_feedback_info += f"\n  + Cần cải thiện: {', '.join([s[0] for s in top_spk_sugg])}"

        slide_audio_compatibility = overall_scores.get('slideAlignment', 0) * 100
        topic_task_relevance = overall_scores.get('contentRelevance', 0) * 100

        course_info = ""
        if course_name:
            course_info += f"\n- Tên môn học: {course_name}"
        if course_description:
            course_info += f"\n- Mô tả môn học: {course_description}"
        if topic_requirements:
            course_info += f"\n- Yêu cầu/Clearning outcomes của topic: {topic_requirements}"

        prompt = f"""Bạn là một chuyên gia đánh giá bài thuyết trình. Hãy viết feedback tổng quan cho bài thuyết trình dựa trên dữ liệu phân tích dưới đây.

Thông tin bài thuyết trình:
- Tiêu đề: {presentation_title}
- Chủ đề: {topic_name}
- Mô tả chủ đề: {topic_description}
{course_info}

Điểm tổng quan:
- Overall Score: {overall_scores.get('overallScore', 0):.2f}/1.0
- Content Relevance: {overall_scores.get('contentRelevance', 0):.2f}/1.0
- Semantic Similarity: {overall_scores.get('semanticSimilarity', 0):.2f}/1.0
- Slide Alignment: {overall_scores.get('slideAlignment', 0):.2f}/1.0

Các vấn đề chung phổ biến nhất:
{chr(10).join([f"- {issue[0]}" for issue in top_issues])}

Các đề xuất cải thiện chung:
{chr(10).join([f"- {suggestion[0]}" for suggestion in top_suggestions])}

{speaker_feedback_info}

Hãy trả về JSON với các trường sau (KHÔNG có markdown, KHÔNG có giải thích):
{{
  "rating": <điểm đánh giá từ 1-5>,
  "comments": "<đoạn feedback tổng quát, bao gồm đánh giá rõ ràng cho phần trình bày của từng người nói (nếu có), khoảng 500-700 từ, xuống dòng rõ ràng>"
}}

Lưu ý:
- rating phải là số nguyên từ 1-5
- comments phải là text tiếng Việt

Return ONLY the JSON object. No markdown, no explanation."""

        try:
            result_text = self._call_ai(prompt)

            if result_text.startswith('```'):
                result_text = result_text.split('```')[1]
                if result_text.startswith('json'):
                    result_text = result_text[4:]
            result_text = result_text.strip().strip('`')

            result_text = ''.join(char for char in result_text if ord(char) >= 32 or char in '\n\t\r')
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]

            result = json.loads(result_text)

            rating = int(result.get('rating', 3))
            comments = str(result.get('comments', ''))
            rating = max(1, min(5, rating))

            logger.info(f"✅ Generated feedback: rating={rating}, comments_length={len(comments)}")

            return {
                'rating': rating,
                'overall_score': overall_scores.get('overallScore', 0),
                'comments': comments,
                'feedback_type': 'ai_report'
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI feedback response: {e}")
            return self._generate_feedback_fallback(overall_scores, top_issues, top_suggestions)
        except Exception as e:
            logger.warning(f"AI API error generating feedback: {e}")
            return self._generate_feedback_fallback(overall_scores, top_issues, top_suggestions)

    def _generate_feedback_fallback(
        self,
        overall_scores: Dict,
        top_issues: list,
        top_suggestions: list
    ) -> Dict[str, Any]:
        """Generate basic feedback without AI if AI fails"""
        overall_score = overall_scores.get('overallScore', 0)
        content_relevance = overall_scores.get('contentRelevance', 0)
        semantic_similarity = overall_scores.get('semanticSimilarity', 0)
        slide_alignment = overall_scores.get('slideAlignment', 0)

        rating = round(overall_score * 5)
        rating = max(1, min(5, rating))

        slide_audio_compatibility = slide_alignment * 100
        topic_task_relevance = content_relevance * 100

        strengths = []
        weaknesses = []
        suggestions = []

        if content_relevance >= 0.7:
            strengths.append("1) Nội dung và độ chính xác: Nội dung liên quan tốt đến chủ đề")
        elif content_relevance < 0.5:
            weaknesses.append("1) Nội dung và độ chính xác: Cần tập trung hơn vào chủ đề chính")

        if semantic_similarity >= 0.7:
            strengths.append("2) Cấu trúc và logic: Trình bày rõ ràng, mạch lạc")
        elif semantic_similarity < 0.5:
            weaknesses.append("2) Cấu trúc và logic: Cần cải thiện cách sắp xếp nội dung")

        if overall_score >= 0.7:
            strengths.append("3) Kỹ năng thuyết trình: Trình bày tốt")
        elif overall_score < 0.5:
            weaknesses.append("3) Kỹ năng thuyết trình: Cần cải thiện")

        strengths.append("4) Làm việc nhóm: (Cần đánh giá thêm từ video)")

        if slide_alignment >= 0.7:
            strengths.append(f"5) Tương thích Slide – Audio: Tốt ({slide_audio_compatibility:.1f}%)")
        elif slide_alignment < 0.5:
            weaknesses.append(f"5) Tương thích Slide – Audio: Cần cải thiện ({slide_audio_compatibility:.1f}%)")

        if content_relevance >= 0.7:
            strengths.append(f"6) Phù hợp với yêu cầu đề tài: Tốt ({topic_task_relevance:.1f}%)")
        elif content_relevance < 0.5:
            weaknesses.append(f"6) Phù hợp với yêu cầu đề tài: Cần cải thiện ({topic_task_relevance:.1f}%)")

        for suggestion, _ in top_suggestions[:3]:
            suggestions.append(suggestion)

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

    # ============================================================
    # TEAMWORK ANALYSIS METHODS
    # ============================================================

    def analyze_teamwork(self, transcript_data: Dict[str, Any]) -> 'TeamworkAnalysisResult':
        """Analyze teamwork aspects of a group presentation"""
        logger.info(f"🔍 Analyzing teamwork for presentation...")

        segments = transcript_data.get('segments', [])
        speakers = transcript_data.get('speakers', [])

        if not segments or len(speakers) < 2:
            return TeamworkAnalysisResult(
                participation_balance={"status": "insufficient_data"},
                speaker_transitions={"status": "insufficient_data"},
                topic_continuity={"status": "insufficient_data"},
                overall_teamwork_score=0.0,
                feedback="Dữ liệu không đủ để phân tích làm việc nhóm. Cần có ít nhất 2 người nói và nhiều đoạn transcript."
            )

        participation = self._analyze_participation_balance(segments, speakers)
        transitions = self._analyze_speaker_transitions(segments)
        continuity = self._analyze_topic_continuity(segments)

        overall_score = self._calculate_teamwork_score(participation, transitions, continuity)
        feedback = self._generate_teamwork_feedback(participation, transitions, continuity, overall_score)

        logger.info(f"✅ Teamwork analysis complete: score={overall_score:.2f}")

        return TeamworkAnalysisResult(
            participation_balance=participation,
            speaker_transitions=transitions,
            topic_continuity=continuity,
            overall_teamwork_score=overall_score,
            feedback=feedback
        )

    def _analyze_participation_balance(self, segments: List[Dict], speakers: List[Dict]) -> Dict[str, Any]:
        """Analyze participation balance among speakers"""
        speaker_stats = {}

        for seg in segments:
            speaker_id = seg.get('speakerId')
            speaker_name = seg.get('speakerName', f'Speaker {speaker_id}')

            if speaker_id is None:
                continue

            if speaker_id not in speaker_stats:
                speaker_stats[speaker_id] = {
                    'name': speaker_name,
                    'word_count': 0,
                    'segment_count': 0,
                    'total_duration': 0.0
                }

            word_count = seg.get('wordCount', 0) or 0
            start_time = float(seg.get('startTimestamp', 0) or 0)
            end_time = float(seg.get('endTimestamp', 0) or 0)
            duration = end_time - start_time if end_time > start_time else 0

            speaker_stats[speaker_id]['word_count'] += word_count
            speaker_stats[speaker_id]['segment_count'] += 1
            speaker_stats[speaker_id]['total_duration'] += duration

        if not speaker_stats:
            return {"status": "no_speaker_data", "details": {}}

        total_words = sum(s['word_count'] for s in speaker_stats.values())
        total_duration = sum(s['total_duration'] for s in speaker_stats.values())

        speaker_list = []
        ideal_percentage = 100 / len(speaker_stats) if speaker_stats else 100
        for sid, stats in speaker_stats.items():
            word_pct = (stats['word_count'] / total_words * 100) if total_words > 0 else 0
            duration_pct = (stats['total_duration'] / total_duration * 100) if total_duration > 0 else 0
            speaker_list.append({
                'speaker_id': sid,
                'name': stats['name'],
                'word_count': stats['word_count'],
                'word_percentage': round(word_pct, 1),
                'segment_count': stats['segment_count'],
                'duration_seconds': round(stats['total_duration'], 1),
                'duration_percentage': round(duration_pct, 1)
            })

        if len(speaker_list) > 1:
            percentages = [s['word_percentage'] for s in speaker_list]
            ideal_pct = 100 / len(speaker_list)
            variance = sum(abs(p - ideal_pct) for p in percentages) / len(percentages)
            balance_score = max(0, 1 - (variance / 100))
        else:
            balance_score = 1.0

        if balance_score >= 0.8:
            status = "excellent"
            status_text = "Phân chia rất cân bằng"
        elif balance_score >= 0.6:
            status = "good"
            status_text = "Phân chia khá cân bằng"
        elif balance_score >= 0.4:
            status = "fair"
            status_text = "Phân chia chưa đều"
        else:
            status = "poor"
            status_text = "Mất cân bằng nghiêm trọng"

        outliers = []
        for s in speaker_list:
            if s['word_percentage'] < ideal_percentage * 0.5:
                outliers.append(f"{s['name']} nói quá ít ({s['word_percentage']:.1f}%)")
            elif s['word_percentage'] > ideal_percentage * 1.5:
                outliers.append(f"{s['name']} nói quá nhiều ({s['word_percentage']:.1f}%)")

        return {
            "status": status,
            "status_text": status_text,
            "balance_score": round(balance_score, 3),
            "speakers": speaker_list,
            "total_words": total_words,
            "total_duration_seconds": round(total_duration, 1),
            "ideal_percentage_per_speaker": round(ideal_percentage, 1),
            "outliers": outliers
        }

    def _analyze_speaker_transitions(self, segments: List[Dict]) -> Dict[str, Any]:
        """Analyze how smoothly speakers transition between each other"""
        if len(segments) < 2:
            return {"status": "insufficient_data", "transitions": [], "transition_score": 0.0}

        transitions = []
        prev_speaker_id = None

        for seg in segments:
            speaker_id = seg.get('speakerId')
            if speaker_id is not None and speaker_id != prev_speaker_id:
                if prev_speaker_id is not None:
                    prev_name = f"Speaker {prev_speaker_id}"
                    curr_name = f"Speaker {speaker_id}"
                    for s in segments:
                        if s.get('speakerId') == prev_speaker_id:
                            prev_name = s.get('speakerName', prev_name)
                        if s.get('speakerId') == speaker_id:
                            curr_name = s.get('speakerName', curr_name)

                    transitions.append({
                        "from": prev_speaker_id,
                        "from_name": prev_name,
                        "to": speaker_id,
                        "to_name": curr_name
                    })
                prev_speaker_id = speaker_id

        unique_transitions = len(set((t['from'], t['to']) for t in transitions))
        total_transitions = len(transitions)

        transition_score = 0.0
        if total_transitions > 0:
            same_speaker_count = sum(1 for i in range(len(segments)-1)
                                   if segments[i].get('speakerId') == segments[i+1].get('speakerId')
                                   and segments[i].get('speakerId') is not None)

            smoothness = unique_transitions / max(total_transitions, 1)
            transition_score = smoothness * (1 - same_speaker_count / max(len(segments), 1))

        if transition_score >= 0.7:
            status = "excellent"
            status_text = "Chuyển lượt rất mượt mà"
        elif transition_score >= 0.5:
            status = "good"
            status_text = "Chuyển lượt khá tốt"
        elif transition_score >= 0.3:
            status = "fair"
            status_text = "Chuyển lượt cần cải thiện"
        else:
            status = "poor"
            status_text = "Chuyển lượt chưa mượt"

        has_turn_taking = len(set(t['from'] for t in transitions)) >= 2
        pattern = "Có sự luân phiên giữa các thành viên" if has_turn_taking else "Một người nói chiếm phần lớn"

        return {
            "status": status,
            "status_text": status_text,
            "transition_score": round(transition_score, 3),
            "total_transitions": total_transitions,
            "unique_transitions": unique_transitions,
            "transitions": transitions[:10],
            "has_turn_taking": has_turn_taking,
            "pattern": pattern
        }

    def _analyze_topic_continuity(self, segments: List[Dict]) -> Dict[str, Any]:
        """Analyze topic continuity between speakers"""
        if len(segments) < 2:
            return {"status": "insufficient_data", "continuity_score": 0.0}

        segment_topics = []
        for seg in segments:
            text = seg.get('segmentText', '') or ''
            speaker_id = seg.get('speakerId')
            speaker_name = seg.get('speakerName', f'Speaker {speaker_id}')

            words = text.lower().split()
            stop_words = {'the', 'and', 'is', 'to', 'a', 'of', 'in', 'for', 'it', 'on', 'that', 'this',
                         'và', 'là', 'của', 'trong', 'được', 'với', 'cho', 'từ', 'này', 'đó', 'các',
                         'um', 'uh', 'ah', 'eh', 'okay', 'so', 'well', 'like', 'just'}
            keywords = [w for w in words if len(w) > 3 and w not in stop_words][:5]

            segment_topics.append({
                'segment_id': seg.get('segmentId'),
                'speaker_id': speaker_id,
                'speaker_name': speaker_name,
                'text': text[:100],
                'keywords': keywords
            })

        continuity_score = 0.5
        topic_matches = 0
        total_transitions = 0

        for i in range(len(segment_topics) - 1):
            curr = segment_topics[i]
            next_seg = segment_topics[i + 1]

            if curr['speaker_id'] != next_seg['speaker_id'] and curr['speaker_id'] is not None:
                total_transitions += 1
                curr_keywords = set(curr['keywords'])
                next_keywords = set(next_seg['keywords'])
                overlap = curr_keywords.intersection(next_keywords)
                if overlap:
                    topic_matches += 1

        if total_transitions > 0:
            continuity_score = topic_matches / total_transitions

        if continuity_score >= 0.6:
            status = "excellent"
            status_text = "Nội dung tiếp nối rất tốt"
        elif continuity_score >= 0.4:
            status = "good"
            status_text = "Nội dung tiếp nối khá tốt"
        elif continuity_score >= 0.2:
            status = "fair"
            status_text = "Nội dung còn rời rạc"
        else:
            status = "poor"
            status_text = "Nội dung rời rạc, thiếu tiếp nối"

        speaker_topics = {}
        for topic in segment_topics:
            sid = topic['speaker_id']
            if sid not in speaker_topics:
                speaker_topics[sid] = {'name': topic['speaker_name'], 'topics': set()}
            speaker_topics[sid]['topics'].update(topic['keywords'])

        return {
            "status": status,
            "status_text": status_text,
            "continuity_score": round(continuity_score, 3),
            "topic_matches": topic_matches,
            "total_speaker_transitions": total_transitions,
            "speaker_topic_overview": [
                {'name': v['name'], 'topic_count': len(v['topics'])}
                for v in speaker_topics.values()
            ]
        }

    def _calculate_teamwork_score(self, participation: Dict, transitions: Dict, continuity: Dict) -> float:
        """Calculate overall teamwork score from individual metrics"""
        participation_score = participation.get('balance_score', 0.5)
        transition_score = transitions.get('transition_score', 0.5)
        continuity_score = continuity.get('continuity_score', 0.5)

        available_scores = [s for s in [participation_score, transition_score, continuity_score] if s > 0]
        if not available_scores:
            return 0.0

        overall = (
            participation_score * 0.4 +
            transition_score * 0.3 +
            continuity_score * 0.3
        )

        return round(overall, 3)

    def _generate_teamwork_feedback(self, participation: Dict, transitions: Dict, continuity: Dict, overall_score: float) -> str:
        """Generate Vietnamese feedback for teamwork"""

        feedback_parts = []
        feedback_parts.append("📊 **PHÂN TÍCH LÀM VIỆC NHÓM**\n")

        if overall_score >= 0.7:
            feedback_parts.append("✅ **Đánh giá chung:** Nhóm làm việc hiệu quả, có sự phối hợp tốt giữa các thành viên.")
        elif overall_score >= 0.5:
            feedback_parts.append("⚠️ **Đánh giá chung:** Nhóm có sự cố gắng nhưng cần cải thiện một số khía cạnh về phối hợp.")
        else:
            feedback_parts.append("❌ **Đánh giá chung:** Cần có sự cải thiện đáng kể trong cách làm việc nhóm.")

        feedback_parts.append("\n---")
        feedback_parts.append("### 1️⃣ MỨC ĐỘ THAM GIA CỦA CÁC THÀNH VIÊN")
        if participation.get('status') not in ['insufficient_data', 'no_speaker_data']:
            feedback_parts.append(f"**Trạng thái:** {participation.get('status_text', 'N/A')}")
            feedback_parts.append(f"**Điểm cân bằng:** {participation.get('balance_score', 0):.2f}/1.0")

            feedback_parts.append("\n**Chi tiết từng thành viên:**")
            for speaker in participation.get('speakers', []):
                feedback_parts.append(
                    f"- {speaker['name']}: {speaker['word_count']} từ ({speaker['word_percentage']:.1f}%), "
                    f"{speaker['segment_count']} đoạn, {speaker['duration_seconds']:.1f}s)"
                )

            outliers = participation.get('outliers', [])
            if outliers:
                feedback_parts.append("\n**⚠️ Vấn đề phân bổ:**")
                for outlier in outliers:
                    feedback_parts.append(f"- {outlier}")

            if participation.get('balance_score', 0) < 0.6:
                feedback_parts.append("\n**💡 Gợi ý:**")
                feedback_parts.append("- Các thành viên nên phân chia nội dung công bằng hơn")
                feedback_parts.append("- Người nói ít nên được giao phần trình bày nhiều hơn")
        else:
            feedback_parts.append("Không đủ dữ liệu để phân tích.")

        feedback_parts.append("\n---")
        feedback_parts.append("### 2️⃣ SỰ CHUYỂN LƯỢT GIỮA CÁC THÀNH VIÊN")
        if transitions.get('status') != 'insufficient_data':
            feedback_parts.append(f"**Trạng thái:** {transitions.get('status_text', 'N/A')}")
            feedback_parts.append(f"**Điểm chuyển lượt:** {transitions.get('transition_score', 0):.2f}/1.0")
            feedback_parts.append(f"**Tổng số lần chuyển lượt:** {transitions.get('total_transitions', 0)}")
            feedback_parts.append(f"**Mẫu chuyển lượt:** {transitions.get('pattern', 'N/A')}")

            if transitions.get('transition_score', 0) < 0.5:
                feedback_parts.append("\n**💡 Gợi ý:**")
                feedback_parts.append("- Các thành viên nên chuyển lượt mượt mà hơn")
                feedback_parts.append("- Sử dụng câu chuyển tiếp: 'Xin nhường cho bạn X', 'Tiếp theo là phần của...'")
        else:
            feedback_parts.append("Không đủ dữ liệu để phân tích.")

        feedback_parts.append("\n---")
        feedback_parts.append("### 3️⃣ SỰ TIẾP NỐI NỘI DUNG GIỮA CÁC THÀNH VIÊN")
        if continuity.get('status') != 'insufficient_data':
            feedback_parts.append(f"**Trạng thái:** {continuity.get('status_text', 'N/A')}")
            feedback_parts.append(f"**Điểm tiếp nối:** {continuity.get('continuity_score', 0):.2f}/1.0")
            feedback_parts.append(f"**Số lần chuyển chủ đề:** {continuity.get('topic_matches', 0)}/{continuity.get('total_speaker_transitions', 0)}")

            if continuity.get('continuity_score', 0) < 0.5:
                feedback_parts.append("\n**💡 Gợi ý:**")
                feedback_parts.append("- Các thành viên nên lắng nghe và tiếp nối ý của người trước")
                feedback_parts.append("- Tránh lặp lại nội dung đã được trình bày")
        else:
            feedback_parts.append("Không đủ dữ liệu để phân tích.")

        feedback_parts.append("\n---")
        feedback_parts.append("### 📋 TỔNG KẾT")
        feedback_parts.append(f"**Điểm teamwork tổng thể:** {overall_score:.2f}/1.0")

        if overall_score >= 0.8:
            rating_text = "Xuất sắc"
        elif overall_score >= 0.6:
            rating_text = "Tốt"
        elif overall_score >= 0.4:
            rating_text = "Trung bình"
        else:
            rating_text = "Cần cải thiện"

        feedback_parts.append(f"**Xếp loại:** {rating_text}")

        return "\n".join(feedback_parts)

    # ============================================================
    # RUBRIC-BASED SCORING METHODS
    # ============================================================

    @staticmethod
    def _rubric_row_id(criterion: Dict) -> Any:
        cid = criterion.get("criteriaId")
        if cid is not None:
            return cid
        return criterion.get("classRubricCriteriaId")

    @staticmethod
    def _heuristic_score_factor(
        criteria_name: str,
        overall_scores: Dict,
        speech_quality: Dict = None,
    ) -> float:
        """Map criterion name to a 0–1 factor from existing analysis signals."""
        overall_scores = overall_scores or {}
        n = (criteria_name or "").lower()
        slide_keys = ("slide", "slides", "powerpoint", "trang chiếu")
        voice_keys = ("voice", "speech", "giọng", "âm thanh", "fluency", "delivery", "oral")
        if any(k in n for k in slide_keys):
            return float(overall_scores.get("slideAlignment") or overall_scores.get("overallScore") or 0)
        if any(k in n for k in voice_keys):
            if speech_quality and speech_quality.get("overallScore") is not None:
                ov = float(speech_quality["overallScore"])
                return (ov / 100.0) if ov > 1.0 else ov
            return float(overall_scores.get("overallScore") or 0)
        rel = float(overall_scores.get("contentRelevance") or 0)
        sem = float(overall_scores.get("semanticSimilarity") or 0)
        if rel or sem:
            return (rel * 0.5 + sem * 0.5)
        return float(overall_scores.get("overallScore") or 0)

    def _fill_missing_rubric_criteria(
        self,
        rubric_criteria: List[Dict],
        scores_dict: Dict[str, Any],
        overall_scores: Dict,
        speech_quality: Dict = None,
    ) -> Dict[str, Any]:
        """Ensure every class rubric row has an entry (AI often returns only one criterion)."""
        for criterion in rubric_criteria or []:
            raw_id = self._rubric_row_id(criterion)
            if raw_id is None:
                continue
            key = str(raw_id)
            if key in scores_dict and scores_dict[key]:
                continue
            name = criterion.get("criteriaName", criterion.get("criteria_name", ""))
            max_score = float(criterion.get("maxScore") or 100)
            weight = float(criterion.get("weight") or 0)
            factor = self._heuristic_score_factor(name, overall_scores, speech_quality)
            score = round(factor * max_score, 2)
            try:
                cid_val = int(raw_id)
            except (TypeError, ValueError):
                cid_val = raw_id
            scores_dict[key] = {
                "criteriaId": cid_val,
                "criteriaName": name,
                "score": score,
                "maxScore": max_score,
                "weight": weight,
                "comment": self._build_fallback_comment(
                    name, score, max_score, speech_quality, overall_scores,
                    segment_analyses=None, analysis_results=None,
                ),
                "suggestions": self._build_fallback_suggestions(
                    name, score, max_score, speech_quality, overall_scores,
                    segment_analyses=None, analysis_results=None,
                ),
            }
            logger.warning(f"   ↳ Filled missing rubric criterion id={key} ({name}) with heuristic score")
        return scores_dict

    @staticmethod
    def _weighted_overall_from_criteria(scores_dict: Dict[str, Any]) -> float:
        """Overall 0–1 as weighted average of normalized criterion scores (score/maxScore)."""
        total_weighted_score = 0.0
        total_weight = 0.0
        
        for cs in (scores_dict or {}).values():
            max_v = float(cs.get("maxScore") or 100)
            sc = float(cs.get("score") or 0)
            weight = float(cs.get("weight") or 0)
            
            if max_v <= 0:
                continue
                
            normalized_score = sc / max_v
            total_weighted_score += normalized_score * weight
            total_weight += weight

        if total_weight <= 0:
            # Fallback to simple average if no weights provided
            normalized_scores = []
            for cs in (scores_dict or {}).values():
                max_v = float(cs.get("maxScore") or 100)
                sc = float(cs.get("score") or 0)
                if max_v <= 0:
                    continue
                normalized_scores.append(sc / max_v)
            
            if not normalized_scores:
                return 0.0
            
            average = sum(normalized_scores) / len(normalized_scores)
            return min(1.0, max(0.0, average))

        result = total_weighted_score / total_weight
        return min(1.0, max(0.0, result))

    def _build_vietnamese_report_summary(
        self,
        weighted_overall: float,
        criterion_scores_dict: Dict[str, Any],
        dim_scores: Optional[Dict],
        rubric_criteria: Optional[List[Dict]] = None,
        speech_quality: Optional[Dict] = None,
    ) -> str:
        """Khối text chuẩn: tiêu đề, điểm rubric, từng tiêu chí (chuẩn hoá /1.0), 3 chỉ số semantic."""
        lines = [
            "BÁO CÁO ĐÁNH GIÁ BÀI THUYẾT TRÌNH",
            "",
            f"Điểm tổng kết (theo rubric): {weighted_overall:.2f}/1.0",
            "",
        ]
        ordered_keys: List[str] = []
        if rubric_criteria:
            for c in rubric_criteria:
                rid = self._rubric_row_id(c)
                if rid is not None:
                    ordered_keys.append(str(rid))
        else:
            ordered_keys = list((criterion_scores_dict or {}).keys())

        for rid in ordered_keys:
            cs = (criterion_scores_dict or {}).get(rid)
            if not cs or not isinstance(cs, dict):
                continue
            name = cs.get("criteriaName", "Tiêu chí")
            score = float(cs.get("score") or 0)
            max_s = float(cs.get("maxScore") or 1) or 1.0
            norm = (score / max_s) if max_s else 0.0
            lines.append(f"{name}: {norm:.2f}/1.0")

        lines.append("")
        ds = dim_scores or {}
        lines.append(
            f"Nội dung và độ chính xác: {float(ds.get('contentRelevance', 0) or 0):.2f}/1.0"
        )
        lines.append(
            f"Tương đồng ngữ nghĩa: {float(ds.get('semanticSimilarity', 0) or 0):.2f}/1.0"
        )
        lines.append(
            f"Tương thích Slide - Audio: {float(ds.get('slideAlignment', 0) or 0):.2f}/1.0"
        )

        text = "\n".join(lines)
        if speech_quality:
            text += f"""

Chất lượng giọng nói:
- Fluency: {speech_quality.get('fluencyScore', 'N/A')}
- Clarity: {speech_quality.get('clarityScore', 'N/A')}
- Confidence: {speech_quality.get('confidenceScore', 'N/A')}
"""
        return text

    def calculate_rubric_scores(
        self,
        presentation_title: str,
        topic_name: str,
        topic_description: str,
        segment_analyses: List[Dict],
        overall_scores: Dict,
        speech_quality: Dict = None,
        hesitation_patterns: List[Dict] = None,
        segment_speech_quality: List[Dict] = None,
        analysis_results: Dict = None,
        rubric_criteria: List[Dict] = None,
        settings: Dict = None,
        course_name: str = None,
        course_description: str = None,
        topic_requirements: str = None,
        speakers: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate scores based on rubric criteria using AI
        
        Args:
            presentation_title: Title of the presentation
            topic_name: Topic name
            topic_description: Topic description
            segment_analyses: List of segment analyses from semantic worker
            overall_scores: Overall scores from semantic analysis
            speech_quality: Speech quality analysis data
            hesitation_patterns: List of hesitation patterns
            segment_speech_quality: Speech quality per segment
            analysis_results: Overall analysis results with quality metrics
            rubric_criteria: List of rubric criteria from class
            settings: AI settings
            course_name: Course name
            course_description: Course description
            topic_requirements: Topic requirements/clearning outcomes
            
        Returns:
            Dict with criterion_scores, report_content, overall_scores
        """
        logger.info(f"🎯 Calculating rubric-based scores with {self.ai_provider.upper()} AI...")

        if rubric_criteria:
            for criterion in rubric_criteria:
                if criterion.get("criteriaId") is None and criterion.get("classRubricCriteriaId") is not None:
                    criterion["criteriaId"] = criterion["classRubricCriteriaId"]

        expected_ids = [
            str(self._rubric_row_id(c))
            for c in (rubric_criteria or [])
            if self._rubric_row_id(c) is not None
        ]
        rubric_count = len(expected_ids)
        ids_line = ", ".join(expected_ids) if expected_ids else "(không có)"

        # Prepare rubric data for prompt
        rubric_text = ""
        if rubric_criteria:
            for idx, criterion in enumerate(rubric_criteria, 1):
                criteria_name = criterion.get('criteriaName', criterion.get('criteria_name', 'Unknown'))
                criteria_desc = criterion.get('criteriaDescription', criterion.get('criteria_description', ''))
                weight = criterion.get('weight', 1.0)
                max_score = criterion.get('maxScore', 10)
                row_id = self._rubric_row_id(criterion)
                rubric_text += f"""
{idx}. criteriaId (bắt buộc giữ nguyên số này trong JSON): {row_id}
   - Tên: {criteria_name} (Trọng số: {weight}, Điểm tối đa: {max_score})
   - Mô tả: {criteria_desc}
"""
        
        # Prepare speech quality data
        speech_text = ""
        if speech_quality:
            # Audio duration for reference
            audio_duration = speech_quality.get('audioDuration')
            audio_info = f"- Audio Duration: {audio_duration:.1f}s" if audio_duration else ""

            speech_text = f"""
- Fluency Score: {speech_quality.get('fluencyScore', 'N/A')}
- Clarity Score: {speech_quality.get('clarityScore', 'N/A')}
- Confidence Score: {speech_quality.get('confidenceScore', 'N/A')}
- Overall Speech Score: {speech_quality.get('overallScore', 'N/A')}
- Speaking Rate: {speech_quality.get('speakingRate', 'N/A')} syllables/min
- Speech Rhythm Score: {speech_quality.get('speechRhythmScore', 'N/A')}
- Silence Ratio: {speech_quality.get('silenceRatio', 'N/A')}
- Voiced Ratio: {speech_quality.get('voicedRatio', 'N/A')}
- Pitch: Mean={speech_quality.get('pitchMean', 'N/A')}, Std={speech_quality.get('pitchStd', 'N/A')}, Variation={speech_quality.get('pitchVariation', 'N/A')}
- Energy: Mean={speech_quality.get('energyMean', 'N/A')}, Std={speech_quality.get('energyStd', 'N/A')}, Volume Variation={speech_quality.get('volumeVariation', 'N/A')}
- Total Hesitations: {speech_quality.get('totalHesitationCount', 0)} times
- Total Hesitation Time: {(speech_quality.get('totalHesitationTime') or 0):.1f}s
- Hesitation Rate: {(speech_quality.get('hesitationRate') or 0):.2f} times/min
- Spectral Centroid Mean (Timbre): {speech_quality.get('spectralCentroidMean', 'N/A')}
- Technical Info: FileSize={speech_quality.get('audioFileSize', 'N/A')} bytes, SampleRate={speech_quality.get('sampleRate', 'N/A')}Hz, Config={speech_quality.get('opensmileConfig', 'N/A')}
{audio_info}
"""

        if hesitation_patterns:
            speech_text += f"\n- Hesitation Patterns Detail ({len(hesitation_patterns)} patterns):\n"
            # Show top 10 patterns to avoid context bloat
            for p in hesitation_patterns[:10]:
                ptype = p.get('patternType', 'unknown')
                dur = p.get('duration', 0)
                desc = p.get('description', '')
                speech_text += f"  * {ptype} at {p.get('startTime')}s, duration: {dur}s. {desc}\n"

        if segment_speech_quality:
            speech_text += f"\n- Segment Speech Quality (Summarized):\n"
            # Just show segments with low confidence or high hesitation
            for ssq in segment_speech_quality:
                if (ssq.get('confidenceScore', 1) or 1) < 0.6 or (ssq.get('segmentHesitationCount', 0) or 0) > 2:
                    issues = ssq.get('qualityIssues', '[]')
                    if isinstance(issues, str):
                        try: issues = json.loads(issues)
                        except: issues = []
                    speech_text += f"  * Segment {ssq.get('segmentId')}: Conf={ssq.get('confidenceScore')}, Hes={ssq.get('segmentHesitationCount')}. Issues: {', '.join(issues) if issues else 'None'}\n"
        
        # Prepare segment analysis summary
        segment_summary = ""
        if segment_analyses:
            total = len(segment_analyses)
            avg_relevance = sum(float(sa.get('relevanceScore', 0) or 0) for sa in segment_analyses) / total if total > 0 else 0
            avg_semantic = sum(float(sa.get('semanticScore', 0) or 0) for sa in segment_analyses) / total if total > 0 else 0
            avg_alignment = sum(float(sa.get('alignmentScore', 0) or 0) for sa in segment_analyses) / total if total > 0 else 0
            
            segment_summary = f"""
- Total Segments Analyzed: {total}
- Average Relevance Score: {avg_relevance:.2f}/1.0
- Average Semantic Score: {avg_semantic:.2f}/1.0
- Average Alignment Score: {avg_alignment:.2f}/1.0
- Overall Score: {float(overall_scores.get('overallScore') or 0):.2f}/1.0

### Dữ liệu cụ thể từng phân đoạn (Segment Details):
"""
            # Add details for "interesting" segments (lowest scores or specific issues)
            # Sort by total score ascending
            sorted_segs = sorted(segment_analyses, key=lambda x: (x.get('relevanceScore', 1) or 1) + (x.get('semanticScore', 1) or 1) + (x.get('alignmentScore', 1) or 1))
            
            # Take top 10 worst/interesting segments to provide context
            for sa in sorted_segs[:10]:
                seg_id = sa.get('segmentId')
                txt = sa.get('segmentText', '')[:100] + "..."
                rel_expl = sa.get('relevanceExplanation', '')
                mis_reason = sa.get('misalignmentReason', '')
                status = sa.get('alignmentStatus', 'unknown')
                speaker = sa.get('speakerLabel') or sa.get('speakerName') or 'Không xác định'
                
                segment_summary += f"- Segment {seg_id} (Speaker: {speaker}, Score: R:{sa.get('relevanceScore')}, S:{sa.get('semanticScore')}, A:{sa.get('alignmentScore')}):\n"
                segment_summary += f"  * Text: \"{txt}\"\n"
                if rel_expl: segment_summary += f"  * Relevance Expl: {rel_expl}\n"
                if status != 'aligned': segment_summary += f"  * Alignment: {status} (Reason: {mis_reason})\n"
                if sa.get('matchedConcepts'): segment_summary += f"  * Concepts: {sa.get('matchedConcepts')}\n"
        
        # Prepare AnalysisResults data
        analysis_results_text = ""
        # if analysis_results:
        #     ar = analysis_results
        #     analysis_results_text = f"""
        # ## Dữ liệu từ AnalysisResults (Kết quả phân tích tổng hợp):
        # - Overall Score: {ar.get('overallScore', 'N/A')}
        # - Analyzed At: {ar.get('analyzedAt', 'N/A')}
        # - AI Model Version: {ar.get('aiModelVersion', 'N/A')}
        # - Status: {ar.get('status', 'N/A')}
        # 
        # ### Content Quality (Chất lượng nội dung):
        # {self._format_quality_data(ar.get('contentQuality'), ['coherenceScore', 'depthScore', 'accuracyScore', 'topicCoverageScore', 'strengths', 'weaknesses'])}
        # 
        # ### Delivery Quality (Chất lượng trình bày):
        # {self._format_quality_data(ar.get('deliveryQuality'), ['clarityScore', 'pronunciationScore', 'volumeConsistency', 'speechRateWpm', 'voiceQuality'])}
        # 
        # ### Structure Quality (Chất lượng cấu trúc):
        # {self._format_quality_data(ar.get('structureQuality'), ['organizationScore', 'transitionQuality', 'introConclusionScore', 'logicalFlowScore', 'structureNotes'])}
        # 
        # ### Engagement Metrics (Tương tác):
        # {self._format_quality_data(ar.get('engagementMetric'), ['enthusiasmScore', 'variationScore', 'rhetoricalDeviceCount', 'emotionalTone'])}
        # 
        # ### Speech Patterns (Mẫu giọng nói):
        # {self._format_quality_data(ar.get('speechPattern'), ['fillerWordCount', 'avgPauseDuration', 'longPauseCount', 'paceConsistency', 'fillerWordList'])}
        # """
        
        # Build course info
        course_info = ""
        if course_name:
            course_info += f"- Tên môn học: {course_name}\n"
        if course_description:
            course_info += f"- Mô tả môn học: {course_description}\n"
        if topic_requirements:
            course_info += f"- Yêu cầu/Clearning outcomes: {topic_requirements}\n"
        
        # Teamwork/Speakers info
        teamwork_info = ""
        speaker_summary_text = ""
        if segment_analyses:
            speaker_analyses = {}
            for sa in segment_analyses:
                spk = sa.get('speakerLabel') or sa.get('speakerName') or 'Không xác định'
                if spk not in speaker_analyses:
                    speaker_analyses[spk] = {
                        'issues': [],
                        'suggestions': [],
                        'scores': {'rel': [], 'sem': [], 'ali': []}
                    }
                
                def ensure_list(val):
                    if isinstance(val, str):
                        try: return json.loads(val)
                        except: return [val]
                    return val or []

                speaker_analyses[spk]['issues'].extend(ensure_list(sa.get('issues')))
                speaker_analyses[spk]['suggestions'].extend(ensure_list(sa.get('suggestions')))
                speaker_analyses[spk]['scores']['rel'].append(float(sa.get('relevanceScore', 0) or 0))
                speaker_analyses[spk]['scores']['sem'].append(float(sa.get('semanticScore', 0) or 0))
                speaker_analyses[spk]['scores']['ali'].append(float(sa.get('alignmentScore', 0) or 0))

            from collections import Counter
            speaker_summary_text = "## Chi tiết đánh giá theo từng người nói (Speaker-level feedback):\n"
            for spk, data in speaker_analyses.items():
                top_issues = [i[0] for i in Counter(data['issues']).most_common(3)]
                top_suggestions = [s[0] for s in Counter(data['suggestions']).most_common(3)]
                
                avg_rel = sum(data['scores']['rel']) / len(data['scores']['rel']) if data['scores']['rel'] else 0
                avg_sem = sum(data['scores']['sem']) / len(data['scores']['sem']) if data['scores']['sem'] else 0
                avg_ali = sum(data['scores']['ali']) / len(data['scores']['ali']) if data['scores']['ali'] else 0
                
                speaker_summary_text += f"- **{spk}**:\n"
                speaker_summary_text += f"  * Điểm TB: Nội dung {avg_rel:.2f}, Logic {avg_sem:.2f}, Slide {avg_ali:.2f}\n"
                if top_issues:
                    speaker_summary_text += f"  * Các vấn đề ghi nhận: {', '.join(top_issues)}\n"
                if top_suggestions:
                    speaker_summary_text += f"  * Gợi ý cụ thể: {', '.join(top_suggestions)}\n"

        if speakers and len(speakers) > 1:
            teamwork_info = "## Dữ liệu về Nhóm & Người thuyết trình (Teamwork Summary):\n"
            for s in speakers:
                label = s.get('aiSpeakerLabel', 'Unknown')
                dur = s.get('totalDurationSeconds', 0)
                segs = s.get('segmentCount', 0)
                mapped = "Đã khớp SV" if s.get('isMapped') else "Chưa khớp"
                teamwork_info += f"- Diễn giả {label}: Nói {dur:.1f}s, {segs} đoạn ({mapped})\n"
            teamwork_info += "- Hãy đánh giá sự cân bằng trong việc phân chia thời lượng trình bày và sự phối hợp giữa các thành viên.\n"
        
        # Create prompt for rubric-based scoring
        prompt = f"""Bạn là chuyên gia đánh giá bài thuyết trình. Hãy đánh giá bài thuyết trình này dựa trên rubric được cung cấp.

## Thông tin bài thuyết trình:
- Tiêu đề: {presentation_title}
- Chủ đề: {topic_name}
- Mô tả chủ đề: {topic_description}
{course_info}
## Điểm phân tích từ Semantic Worker:
{segment_summary}
## Dữ liệu chi tiết theo từng người nói (Speaker Detail):
{speaker_summary_text}
## Dữ liệu chất lượng giọng nói (Speech Quality):
{speech_text if speech_text else "Chưa có dữ liệu phân tích giọng nói"}
{teamwork_info if teamwork_info else ""}
{analysis_results_text if analysis_results_text else ""}
## Rubric Criteria (Tiêu chí đánh giá):
{rubric_text if rubric_text else "Không có rubric criteria"}

## Ràng buộc bắt buộc (vi phạm là sai):
- Danh sách đúng {rubric_count} tiêu chí; criteriaId trong JSON chỉ được là: [{ids_line}]
- Mảng criterion_scores phải có đúng {rubric_count} phần tử (mỗi criteriaId xuất hiện đúng một lần)
- Không gộp nhiều tiêu chí vào một phần tử; không bỏ sót Slide Quality / Voice Quality nếu rubric có các tên tương ứng

## Yêu cầu chính:
1. Đánh giá từng tiêu chí trong rubric dựa trên dữ liệu phân tích
2. Tính điểm cho mỗi tiêu chí (theo thang điểm tối đa của tiêu chí đó) dựa trên bằng chứng thực tế từ Transcript và kết quả phân tích.
3. Tính điểm tổng kết theo trọng số (overallScore thang 0–1).
4. Viết nhận xét chi tiết cho từng tiêu chí (trong từng phần tử criterion_scores và trong reportContent).
5. Đưa ra gợi ý cải thiện cho từng tiêu chí.
6. **NGUYÊN TẮC CHẤM ĐIỂM NGHIÊM NGẶT (CRITICAL):**
   - **Bằng chứng thực tế (Evidence-based):** AI chỉ được cho điểm nếu tìm thấy bằng chứng trong Transcript hoặc Slide. KHÔNG tự suy diễn hoặc cho điểm "khuyến khích".
   - **Đúng trọng tâm (Topic Relevance):** Nếu nội dung người nói không khớp với `topicName` hoặc vi phạm các yêu cầu trong `criteriaDescription`, BẮT BUỘC phải cho điểm thấp (thậm chí 0-2 điểm) và nêu rõ lý do "Lạc đề" hoặc "Thiếu nội dung bắt buộc".
   - **Thẳng thắn (Direct Feedback):** Nhận xét phải mang tính xây dựng nhưng không được né tránh khuyết điểm. Nếu nói tệ, hãy ghi rõ là tệ và chỉ ra tại sao.
   - **Công bằng (Individual Fairness):** Phải phân biệt rõ ràng đóng góp của từng Speaker. Nếu SPEAKER_00 nói tốt nhưng SPEAKER_01 nói lạc đề, điểm số và nhận xét phải phản ánh đúng sự khác biệt này.
7. **QUAN TRỌNG: Với mỗi tiêu chí, phải chỉ rõ ràng từng NGƯỜI NÓI cụ thể (ví dụ: SPEAKER_00, SPEAKER_01) nếu có sự khác biệt hiệu suất giữa các thành viên. Tránh nhận xét chung chung không chỉ danh nhân vật.**
8. **Nhấn mạnh: Nếu một người nói không chịu trách nhiệm hay không tham gia tiêu chí nào đó, phải nêu rõ (ví dụ: "SPEAKER_02 không thực hiện vai trò trong tiêu chí này") để đảm bảo công bằng đánh giá.**

## Trả về JSON với format sau (KHÔNG có markdown, KHÔNG có giải thích):
{{
  "criterion_scores": [
    {{
      "criteriaId": <id của tiêu chí>,
      "criteriaName": "<tên tiêu chí>",
      "score": <điểm đánh giá>,
      "maxScore": <điểm tối đa>,
      "weight": <trọng số>,
      "comment": "<nhận xét chi tiết bằng tiếng Việt>",
      "suggestions": ["<gợi ý 1>", "<gợi ý 2>"]
    }}
  ],
  "overallScore": <điểm tổng (0-1)>,
  "reportBody": {
    "summary": "<đoạn tổng quan ngắn gọn bài thuyết trình, 100-200 từ, tiếng Việt>",
    "speaker_feedback": [
      {
        "speaker": "<Tên người trình bày, vd: SPEAKER_00>",
        "performance_summary": "<Tóm tắt ngắn gọn phần trình bày của người này>",
        "individual_strengths": ["<điểm mạnh cá nhân 1>", "<điểm mạnh cá nhân 2>"],
        "individual_weaknesses": ["<điểm cần cải thiện cá nhân 1>", "<điểm cần cải thiện cá nhân 2>"],
        "individual_suggestions": ["<gợi ý cải thiện cá nhân 1>"]
      }
    ],
    "strengths": ["<điểm mạnh chung của nhóm 1>", "<điểm mạnh chung của nhóm 2>"],
    "weaknesses": ["<điểm cần cải thiện chung của nhóm 1>", "<điểm cần cải thiện chung của nhóm 2>"],
    "suggestions": ["<gợi ý cải thiện chung của nhóm 1>", "<gợi ý cải thiện chung của nhóm 2>"]
  }
}
}}


Lưu ý:
- reportBody phải là object có 5 trường: summary, speaker_feedback, strengths, weaknesses, suggestions (tất cả là text thuần, không có markdown)
- **speaker_feedback: BẮT BUỘC phải có một phần tử cho mỗi người nói (Speaker) xuất hiện trong dữ liệu phân tích. KHÔNG ĐƯỢC bỏ sót hoặc gộp nhiều người vào một phần tử. Mỗi phần tử speaker_feedback phải:**
  * Nêu rõ tên diễn giả (ví dụ: "SPEAKER_00", "SPEAKER_01")
  * Viết nhận xét cụ thể cho người đó (ví dụ: điểm mạnh, điểm yếu, gợi ý riêng)
  * Đánh giá chi tiết về góp phần của từng thành viên trong từng tiêu chí nếu có sự chênh lệch
  * Nếu một người nói không tham gia hoặc không chịu trách nhiệm cho một tiêu chí, phải ghi rõ điều đó
- summary: viết thành một đoạn tổng quan ngắn gọn, tích hợp mô tả cân bằng giữa các thành viên (nếu là nhóm)
- strengths: liệt kê những gì làm tốt (3-5 điểm), nêu rõ ai làm tốt nếu khác biệt
- weaknesses: liệt kê những gì cần cải thiện (3-5 điểm), nêu rõ ai cần cải thiện nếu khác biệt
- suggestions: gợi ý hành động cụ thể để nhóm/cá nhân cải thiện (3-5 điểm)

## Hướng dẫn đánh giá Speech Quality (Voice Quality):
- fluencyScore: Độ trôi chảy (0-1) → cao = tốt
- clarityScore: Độ rõ ràng (0-1) → cao = tốt
- confidenceScore: Độ tự tin (0-1) → cao = tốt
- speakingRate: Tốc độ nói (syllables/min) → tối ưu 120-150 syllables/min
- speechRhythmScore: Nhịp điệu (0-1) → cao = tốt
- silenceRatio: Tỉ lệ im lặng (0-1) → hợp lý < 30%
- totalHesitationCount: Tổng số lần ngập ngừng → ít = tốt
- totalHesitationTime: Tổng thời gian ngập ngừng (giây) → ít = tốt
- hesitationRate: Tỉ lệ ngập ngừng (lần/phút) → ít = tốt
- audioDuration: Thời lượng audio (giây)

**Nếu dữ liệu speech quality có điểm > 0**: Đánh giá chi tiết dựa trên các chỉ số trên
**Nếu dữ liệu speech quality trống hoặc tất cả = 0**: Ghi nhận "Không có dữ liệu phân tích giọng nói" và cho điểm 0, không tự suy đoán điểm số

- Sử dụng alignment / slide để đánh giá tiêu chí về slide
- Sử dụng segment analyses để đánh giá tiêu chí về nội dung và độ liên quan
- **comment trong criterion_scores phải ngắn gọn (1-3 câu), tập trung vào tiêu chí đó. BẮT BUỘC nêu tên diễn giả cụ thể (ví dụ: SPEAKER_00, SPEAKER_01, SPEAKER_02) nếu:**
  * Tiêu chí đó có sự chênh lệch rõ rệt giữa các thành viên
  * Có cá nhân nào làm cực tốt/cực tệ trong phần đó
  * Có người không tham gia hoặc không chịu trách nhiệm cho tiêu chí này
  * Muốn ghi nhận đóng góp riêng của từng thành viên
- suggestions trong criterion_scores là gợi ý riêng cho từng tiêu chí, phải cụ thể (2-3 câu mỗi tiêu chí, nêu rõ cho ai nếu là gợi ý cụ thể cho một người)

Return ONLY the JSON object. No markdown, no explanation."""

        try:
            result = None
            for attempt in range(1, 4):
                try:
                    result_text = self._call_ai(prompt)

                    # Parse AI response
                    if result_text.startswith('```'):
                        result_text = result_text.split('```')[1]
                        if result_text.startswith('json'):
                            result_text = result_text[4:]
                    result_text = result_text.strip().strip('`')

                    # Clean up any non-printable characters
                    result_text = ''.join(char for char in result_text if ord(char) >= 32 or char in '\n\t\r')

                    # Attempt to fix common JSON issues from AI responses
                    result_text = self._fix_ai_json(result_text)

                    result = json.loads(result_text)
                    break  # success

                except QuotaExceededError:
                    raise  # propagate quota errors immediately
                except json.JSONDecodeError as e:
                    if attempt == 3:
                        raise  # propagate to outer try
                    logger.warning(f"   ↳ AI JSON parse attempt {attempt}/3 failed: {e}")

            if result is None:
                raise ValueError("AI returned no parseable response after 3 attempts")

        except QuotaExceededError as e:
            logger.warning(f"AI quota exceeded, using fallback")
            return self._calculate_rubric_scores_fallback(
                segment_analyses,
                overall_scores,
                speech_quality,
                analysis_results,
                rubric_criteria,
                speaker_analyses
            )
        except Exception:
            logger.warning(f"AI rubric scoring failed, using fallback")
            return self._calculate_rubric_scores_fallback(
                segment_analyses,
                overall_scores,
                speech_quality,
                analysis_results,
                rubric_criteria,
                speaker_analyses
            )

        raw_cs = result.get('criterion_scores', [])
        if isinstance(raw_cs, dict):
            criterion_scores = list(raw_cs.values())
        else:
            criterion_scores = raw_cs or []

        report_body = result.get('reportBody', {})
        if not isinstance(report_body, dict):
            report_body = {}
        report_content = ""
        if report_body:
            summary = report_body.get('summary', '')
            speaker_feedback = report_body.get('speaker_feedback', [])
            strengths = report_body.get('strengths', [])
            weaknesses = report_body.get('weaknesses', [])
            suggestions = report_body.get('suggestions', [])

            lines = []
            if summary:
                lines.append(f"TỔNG QUAN: {summary}\n")
            if speaker_feedback:
                lines.append("ĐÁNH GIÁ CHI TIẾT THEO TỪNG THÀNH VIÊN:")
                for sf in speaker_feedback:
                    if isinstance(sf, dict):
                        spk = sf.get('speaker', 'Unknown')
                        perf = sf.get('performance_summary', '')
                        i_strengths = sf.get('individual_strengths', [])
                        i_weaknesses = sf.get('individual_weaknesses', [])
                        i_sugg = sf.get('individual_suggestions', [])
                        
                        lines.append(f"👤 {spk}:")
                        if perf:
                            lines.append(f"  - Tóm tắt: {perf}")
                        if i_strengths:
                            lines.append(f"  - Điểm mạnh: {', '.join(i_strengths)}")
                        if i_weaknesses:
                            lines.append(f"  - Cần cải thiện: {', '.join(i_weaknesses)}")
                        if i_sugg:
                            lines.append(f"  - Gợi ý riêng: {', '.join(i_sugg)}")
                        lines.append("") # Spacer between speakers
            if strengths:
                lines.append("ĐIỂM MẠNH:")
                for s in strengths:
                    lines.append(f"- {s}")
                lines.append("")
            if weaknesses:
                lines.append("ĐIỂM CẦN CẢI THIỆN:")
                for w in weaknesses:
                    lines.append(f"- {w}")
                lines.append("")
            if suggestions:
                lines.append("GỢI Ý KHẮC PHỤC:")
                for sg in suggestions:
                    lines.append(f"- {sg}")
            report_content = "\n".join(lines)
        else:
            report_content = ""

        overall_score = result.get('overallScore', overall_scores.get('overallScore', 0) if overall_scores else 0)

        # Convert criterion scores to dict format
        criterion_scores_dict = {}
        for cs in criterion_scores:
            if not isinstance(cs, dict):
                continue
            criteria_id = cs.get('criteriaId')
            if criteria_id is None:
                criteria_id = cs.get('criteria_id')
            if criteria_id is not None and criteria_id != '':
                criterion_scores_dict[str(criteria_id)] = cs

        if rubric_criteria:
            before = len(criterion_scores_dict)
            criterion_scores_dict = self._fill_missing_rubric_criteria(
                rubric_criteria,
                criterion_scores_dict,
                overall_scores,
                speech_quality,
            )
            if len(criterion_scores_dict) > before:
                logger.info(f"   ↳ After fill: {len(criterion_scores_dict)} criteria (AI returned {before})")

        overall_score = self._weighted_overall_from_criteria(criterion_scores_dict)

        logger.info(f"✅ Rubric-based scoring complete: {len(criterion_scores_dict)} criteria in output")

        # Update overall scores with rubric-based score
        updated_overall_scores = {
            'overallScore': overall_score,
            'contentRelevance': overall_scores.get('contentRelevance', 0) if overall_scores else 0,
            'semanticSimilarity': overall_scores.get('semanticSimilarity', 0) if overall_scores else 0,
            'slideAlignment': overall_scores.get('slideAlignment', 0) if overall_scores else 0,
            'rubricBased': True
        }

        summary_block = self._build_vietnamese_report_summary(
            overall_score,
            criterion_scores_dict,
            updated_overall_scores,
            rubric_criteria,
            speech_quality,
        )
        detail = report_content.strip()
        report_content = f"{summary_block}\n\n{detail}" if detail else summary_block

        return {
            'criterion_scores': criterion_scores_dict,
            'report_content': report_content,
            'overall_scores': updated_overall_scores,
            'reportBody': report_body,
        }

    def _fix_ai_json(self, text: str) -> str:
        """Attempt to fix common JSON issues in AI responses."""
        lines = text.split('\n')
        fixed_lines = []
        for line in lines:
            # Remove lines that look like instruction fragments (non-JSON text)
            stripped = line.strip()
            if stripped.startswith('## ') or stripped.startswith('**') or stripped.startswith('#'):
                continue
            # Remove trailing commas before } or ]
            if re.search(r',\s*[}\]]', line):
                line = re.sub(r',(\s*[}\]])', r'\1', line)
            fixed_lines.append(line)
        return '\n'.join(fixed_lines)

    def _format_quality_data(self, data: Dict, fields: List[str]) -> str:
        """Format quality data for AI prompt"""
        if not data:
            return "Chưa có dữ liệu"
        
        lines = []
        for field in fields:
            value = data.get(field)
            if value is not None and value != '':
                # Format field name for display
                field_display = field.replace('Score', ' Score').replace('Count', ' Count')
                lines.append(f"- {field_display}: {value}")
        
        return "\n".join(lines) if lines else "Chưa có dữ liệu"

    # ─────────────────────────────────────────────────────────────
    # Fallback feedback builders (called when AI call fails)
    # ─────────────────────────────────────────────────────────────

    def _extract_signal(
        self,
        criteria_name: str,
        overall_scores: Optional[Dict],
        speech_quality: Optional[Dict],
        segment_analyses: Optional[List[Dict]],
        analysis_results: Optional[Dict],
    ) -> Dict[str, Any]:
        """Gom tất cả tín hiệu số cụ thể thành dict thống nhất để dùng chung cho comment & suggestion."""
        n = (criteria_name or "").lower()
        os = overall_scores or {}
        sq = speech_quality or {}
        segs = segment_analyses or []
        ar = analysis_results or {}

        # Ba chỉ số nền tảng (luôn có dù segmentAnalyses trống)
        relevance    = float(os.get("contentRelevance", 0) or 0)
        semantic     = float(os.get("semanticSimilarity", 0) or 0)
        alignment    = float(os.get("slideAlignment", 0) or 0)
        overall      = float(os.get("overallScore", 0) or 0)
        seg_count    = len(segs)

        # Speech quality signals
        sq_overall      = float(sq.get("overallScore", 0) or 0)
        fluency         = float(sq.get("fluencyScore", 0) or 0)
        clarity         = float(sq.get("clarityScore", 0) or 0)
        confidence      = float(sq.get("confidenceScore", 0) or 0)
        hesitation      = int(sq.get("totalHesitationCount", 0) or 0)
        hesitation_time = float(sq.get("totalHesitationTime", 0) or 0)
        hesitation_rate = float(sq.get("hesitationRate", 0) or 0)
        speaking_rate   = float(sq.get("speakingRate", 0) or 0)
        speech_rhythm   = float(sq.get("speechRhythmScore", 0) or 0)
        silence_ratio   = float(sq.get("silenceRatio", 0) or 0)
        audio_duration  = float(sq.get("audioDuration", 0) or 0)
        has_sq_data     = sq_overall > 0 or fluency > 0

        # Content quality từ AnalysisResults (nếu có)
        # cq = ar.get("contentQuality") or {}
        # accuracy = float(cq.get("accuracyScore", 0) or 0)
        # depth    = float(cq.get("depthScore", 0) or 0)
        accuracy = 0.0
        depth = 0.0

        # Slide quality từ AnalysisResults
        # dq = ar.get("deliveryQuality") or {}
        # voice_rate = float(dq.get("speechRateWpm", 0) or 0)
        # voice_qual = float(dq.get("voiceQuality", 0) or 0)
        voice_rate = 0.0
        voice_qual = 0.0

        # Lấy điểm theo category
        if any(k in n for k in ("content", "nội dung", "accuracy", "chính xác")):
            primary_score   = relevance
            secondary_score = semantic
            detail_scores   = {"relevance": relevance, "semantic": semantic,
                               "accuracy": accuracy, "depth": depth}
        elif any(k in n for k in ("slide", "powerpoint", "trang chiếu", "visuals", "hình ảnh")):
            primary_score   = alignment
            secondary_score = relevance
            detail_scores   = {"alignment": alignment, "relevance": relevance}
        elif any(k in n for k in ("voice", "speech", "giọng", "delivery", "oral")):
            primary_score   = sq_overall if sq_overall > 0 else overall
            secondary_score = fluency
            detail_scores   = {"fluency": fluency, "clarity": clarity,
                               "confidence": confidence,
                               "hesitation": hesitation,
                               "speechRate": voice_rate}
        elif any(k in n for k in ("structure", "organization", "cấu trúc", "logical")):
            primary_score   = overall
            secondary_score = alignment
            detail_scores   = {"overall": overall, "alignment": alignment}
        elif any(k in n for k in ("engagement", "tương tác", "interest", "hứng thú")):
            primary_score   = overall
            secondary_score = semantic
            detail_scores   = {"overall": overall, "semantic": semantic}
        else:
            primary_score   = overall
            secondary_score = 0
            detail_scores   = {"overall": overall}

        return {
            "seg_count": seg_count,
            "relevance": relevance, "semantic": semantic, "alignment": alignment,
            "overall": overall,
            "sq_overall": sq_overall, "fluency": fluency, "clarity": clarity,
            "confidence": confidence, "hesitation": hesitation,
            "hesitation_time": hesitation_time, "hesitation_rate": hesitation_rate,
            "speaking_rate": speaking_rate, "speech_rhythm": speech_rhythm,
            "silence_ratio": silence_ratio, "audio_duration": audio_duration,
            "has_sq_data": has_sq_data,
            "voice_rate": voice_rate, "voice_qual": voice_qual,
            "accuracy": accuracy, "depth": depth,
            "primary_score": primary_score,
            "secondary_score": secondary_score,
            "detail_scores": detail_scores,
        }

    def _build_fallback_comment(
        self,
        criteria_name: str,
        score: float,
        max_score: float,
        speech_quality: Optional[Dict] = None,
        overall_scores: Optional[Dict] = None,
        segment_analyses: Optional[List[Dict]] = None,
        analysis_results: Optional[Dict] = None,
        speaker_analyses: Optional[Dict] = None,
    ) -> str:
        """Generate a meaningful comment referencing actual signal numbers (like AI output)."""
        sig = self._extract_signal(
            criteria_name, overall_scores, speech_quality,
            segment_analyses, analysis_results,
        )

        # Identify interesting speakers for this criterion
        spk_note = ""
        if speaker_analyses and len(speaker_analyses) > 0:
            best_spk = None
            worst_spk = None
            best_score = -1
            worst_score = 2
            
            # Map criteria category to score key
            cat_key = 'rel' # Default to relevance
            n_lower = (criteria_name or "").lower()
            if any(k in n_lower for k in ("slide", "powerpoint", "trang chiếu")): cat_key = 'ali'
            elif any(k in n_lower for k in ("voice", "speech", "giọng")): cat_key = 'sem'
            
            for spk, data in speaker_analyses.items():
                scores = data['scores'].get(cat_key, [])
                if scores:
                    avg = sum(scores) / len(scores)
                    if avg > best_score:
                        best_score = avg
                        best_spk = spk
                    if avg < worst_score:
                        worst_score = avg
                        worst_spk = spk
            
            if best_spk and worst_spk and best_spk != worst_spk and (best_score - worst_score) > 0.2:
                spk_note = f" {best_spk} có biểu hiện tốt nhất, trong khi {worst_spk} cần nỗ lực hơn."
            elif best_spk:
                spk_note = f" Tiêu biểu là phần trình bày của {best_spk}."
        norm    = score / max_score if max_score else 0.0
        n       = (criteria_name or "").lower()
        seg_n   = sig["seg_count"]

        # ── Content Quality ───────────────────────────────────────
        if any(k in n for k in ("content", "nội dung")):
            if sig["has_sq_data"]:
                base = (
                    f"Nội dung bài thuyết trình có điểm relevance {sig['relevance']:.2f}/1.0 "
                    f"và semantic {sig['semantic']:.2f}/1.0."
                )
            else:
                base = (
                    f"Không có dữ liệu phân tích semantic chi tiết cho bài thuyết trình này "
                    f"(điểm overall {sig['overall']:.2f}/1.0)."
                )
            if norm >= 0.7:
                return (
                    f"{base} Điểm quy đổi {score:.1f}/{max_score:.0f} — nội dung bám sát đề tài "
                    f"và có độ sâu phù hợp, thể hiện sự chuẩn bị kỹ lưỡng."
                )
            elif norm >= 0.4:
                    acc_part = (
                        f"Điểm accuracy {sig['accuracy']:.2f}/1.0"
                        if sig['accuracy'] > 0
                        else "Chưa có dữ liệu độ chính xác."
                    )
                    return (
                        f"{base} Điểm quy đổi {score:.1f}/{max_score:.0f} — nội dung cơ bản đúng "
                        f"nhưng {'còn thiếu chiều sâu hoặc ví dụ minh họa cụ thể' if sig['depth'] < 0.5 else 'cần được triển khai chi tiết hơn'}. "
                        f"{acc_part} "
                        f"cho thấy vẫn còn{' sai sót về số liệu' if sig['accuracy'] > 0 and sig['accuracy'] < 0.6 else ' chỗ cần kiểm chứng lại'}."
                    )
            else:
                rel_note = (
                    f"Điểm relevance chỉ {sig['relevance']:.2f}/1.0 phản ánh nội dung chưa bám sát mục tiêu học tập."
                    if sig['relevance'] < 0.5 else ""
                )
                sem_note = (
                    f"Điểm semantic {sig['semantic']:.2f}/1.0 cho thấy bài trình bày còn thiếu tính mạch lạc."
                    if sig['semantic'] < 0.5 else ""
                )
                extra = " ".join(p for p in [rel_note, sem_note] if p)
                body_qual = "chưa đáp ứng yêu cầu cốt lõi của môn học" if seg_n > 0 else "rất hạn chế do thiếu dữ liệu phân tích chi tiết"
                return (
                    f"{base} Điểm quy đổi {score:.1f}/{max_score:.0f} — nội dung {body_qual}. "
                    f"{extra}"
                )

        # ── Slide Quality ────────────────────────────────────────
        if any(k in n for k in ("slide", "powerpoint", "trang chiếu", "visuals", "hình ảnh")):
            align_note = ""
            if sig["alignment"] > 0:
                align_note = (
                    f" Điểm Alignment chỉ {sig['alignment']:.2f}/1.0 "
                    f"{'cho thấy các slide chưa trực quan hóa được nội dung audio' if sig['alignment'] < 0.5 else 'phản ánh slide cơ bản đồng bộ với lời nói'}."
                )
            if seg_n > 0:
                seg_note = f" Dữ liệu được tính từ {seg_n} đoạn transcript."
            else:
                seg_note = " Không có dữ liệu phân tích đoạn audio."
            if norm >= 0.7:
                return (
                    f"Chất lượng slide được đánh giá khá tốt với điểm quy đổi {score:.1f}/{max_score:.0f}.{align_note}{seg_note}"
                )
            elif norm >= 0.4:
                return (
                    f"Với điểm quy đổi {score:.1f}/{max_score:.0f}, chất lượng slide ở mức trung bình.{align_note}"
                    f"{' Số lượng segment ' + str(seg_n) + ' cho thấy bài có thể dài dòng hoặc bị chia nhỏ không hợp lý.' if seg_n > 30 else seg_note}"
                )
            else:
                return (
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — chất lượng slide chưa đạt yêu cầu.{align_note}"
                    f"{' Điểm Alignment thấp phản ánh các slide có thể không trực quan hóa được nội dung, khiến người nghe khó theo dõi.' if sig['alignment'] > 0 else ''}"
                    f"{seg_note}"
                )

        # ── Voice Quality ────────────────────────────────────────
        if any(k in n for k in ("voice", "speech", "giọng", "delivery", "oral")):
            if not sig["has_sq_data"]:
                return (
                    f"Không có dữ liệu phân tích giọng nói khả dụng để đánh giá tiêu chí này. "
                    f"Hệ thống ghi nhận trạng thái 'Chưa có dữ liệu phân tích giọng nói'. "
                    f"Điểm số được để ở mức 0 do thiếu dữ liệu đầu vào để xử lý. {spk_note}"
                )
            parts = []
            if sig["fluency"] >= 0.6:
                parts.append(f"trôi chảy ({sig['fluency']:.2f}/1.0)")
            else:
                parts.append(f"ngắt quãng nhiều ({sig['fluency']:.2f}/1.0)")
            if sig["clarity"] >= 0.6:
                parts.append(f"phát âm rõ ({sig['clarity']:.2f}/1.0)")
            else:
                parts.append(f"cần rõ hơn ({sig['clarity']:.2f}/1.0)")
            if sig["confidence"] >= 0.6:
                parts.append(f"tự tin ({sig['confidence']:.2f}/1.0)")
            else:
                parts.append(f"cần tự tin hơn ({sig['confidence']:.2f}/1.0)")
            sq_text = "; ".join(parts)

            # Speaking rate analysis (optimal: 120-150 syllables/min for presentation)
            rate_note = ""
            if sig["speaking_rate"] > 0:
                sr = sig["speaking_rate"]
                if 100 <= sr <= 180:
                    rate_note = f" Tốc độ nói {sr:.0f} syllables/min phù hợp."
                elif sr < 100:
                    rate_note = f" Tốc độ nói {sr:.0f} syllables/min — hơi chậm."
                else:
                    rate_note = f" Tốc độ nói {sr:.0f} syllables/min — hơi nhanh."

            # Hesitation analysis
            hesit_note = ""
            if sig["hesitation"] > 0 or sig["hesitation_time"] > 0:
                hesit_note = f" Ghi nhận {sig['hesitation']} lần ngập ngừng (tổng {sig['hesitation_time']:.1f}s)."
                if sig["hesitation_rate"] > 0:
                    hesit_note += f" Tỉ lệ {sig['hesitation_rate']:.1f} lần/phút."

            # Speech rhythm and silence analysis
            rhythm_note = ""
            if sig["speech_rhythm"] > 0:
                rhythm_note = f" Nhịp điệu speech {sig['speech_rhythm']:.2f}/1.0."
            if sig["silence_ratio"] > 0:
                sr_val = sig["silence_ratio"] * 100
                if sr_val < 30:
                    rhythm_note += f" Tỉ lệ im lặng {sr_val:.1f}% — hợp lý."
                elif sr_val > 50:
                    rhythm_note += f" Tỉ lệ im lặng {sr_val:.1f}% — cao, có thể do ngập ngừng nhiều."

            if norm >= 0.7:
                return (
                    f"Chất lượng giọng nói khá tốt: {sq_text}.{rate_note}{hesit_note}{rhythm_note} "
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — người thuyết trình thể hiện sự chuẩn bị tốt.{spk_note}"
                )
            elif norm >= 0.4:
                return (
                    f"Giọng nói ở mức trung bình: {sq_text}.{rate_note}{hesit_note}{rhythm_note} "
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — cần cải thiện thêm trôi chảy và sự tự tin.{spk_note}"
                )
            else:
                return (
                    f"Chất lượng giọng nói chưa đạt yêu cầu: {sq_text}.{rate_note}{hesit_note}{rhythm_note} "
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — đây là điểm cần được ưu tiên cải thiện.{spk_note}"
                )

        # ── Structure / Organization ──────────────────────────────
        if any(k in n for k in ("structure", "organization", "cấu trúc", "logical")):
            if norm >= 0.7:
                return (
                    f"Với điểm quy đổi {score:.1f}/{max_score:.0f}, bố cục bài trình bày logic, "
                    f"có mở đầu và kết luận rõ ràng, luồng ý chính mạch lạc "
                    f"(overall {sig['overall']:.2f}/1.0)."
                )
            elif norm >= 0.4:
                return (
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — cấu trúc cơ bản đúng nhưng "
                    f"{'cần cải thiện luồng liên kết giữa các phần' if sig['alignment'] < 0.5 else 'cần thêm phần chuyển tiếp rõ ràng hơn'}. "
                    f"Điểm alignment {sig['alignment']:.2f}/1.0."
                )
            else:
                return (
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — cấu trúc bài trình bày "
                    f"thiếu logic rõ ràng, các phần chưa liên kết mạch lạc với nhau. "
                    f"Điểm overall {sig['overall']:.2f}/1.0."
                )

        # ── Engagement ───────────────────────────────────────────
        if any(k in n for k in ("engagement", "tương tác", "interest", "hứng thú")):
            if norm >= 0.7:
                return (
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — bài trình bày thu hút sự chú ý "
                    f"của khán giả, có sự tương tác tốt (overall {sig['overall']:.2f}/1.0)."
                )
            elif norm >= 0.4:
                return (
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — có một số khoảnh khắc hứng thú "
                    f"nhưng chưa đều và cần tăng cường tính tương tác xuyên suốt bài trình bày."
                )
            else:
                return (
                    f"Điểm quy đổi {score:.1f}/{max_score:.0f} — bài trình bày chưa thu hút được "
                    f"sự chú ý của khán giả một cách hiệu quả. Cần thêm ví dụ thực tế, "
                    f"câu hỏi dẫn dắt hoặc tình huống giả định."
                )

        # ── Generic ──────────────────────────────────────────────
        if norm >= 0.7:
            return (
                f"Tiêu chí '{criteria_name}' đạt mức khá với điểm {score:.1f}/{max_score:.0f} "
                f"(overall {sig['overall']:.2f}/1.0). Cần duy trì và phát huy."
            )
        elif norm >= 0.4:
            return (
                f"Tiêu chí '{criteria_name}' đạt mức trung bình với điểm {score:.1f}/{max_score:.0f} "
                f"(overall {sig['overall']:.2f}/1.0). Cần cải thiện thêm để nâng cao điểm tổng kết."
            )
        else:
            return (
                f"Tiêu chí '{criteria_name}' chưa đạt yêu cầu với điểm {score:.1f}/{max_score:.0f} "
                f"(overall {sig['overall']:.2f}/1.0). Cần được ưu tiên cải thiện đáng kể."
            )

    def _build_fallback_suggestions(
        self,
        criteria_name: str,
        score: float,
        max_score: float,
        speech_quality: Optional[Dict] = None,
        overall_scores: Optional[Dict] = None,
        segment_analyses: Optional[List[Dict]] = None,
        analysis_results: Optional[Dict] = None,
    ) -> List[str]:
        """Generate 3 concrete action-item suggestions referencing actual data (like AI output)."""
        sig = self._extract_signal(
            criteria_name, overall_scores, speech_quality,
            segment_analyses, analysis_results,
        )
        norm = score / max_score if max_score else 0.0
        n    = (criteria_name or "").lower()
        suggestions: List[str] = []

        # ── Content Quality ───────────────────────────────────────
        if any(k in n for k in ("content", "nội dung")):
            if norm >= 0.7:
                suggestions.append(
                    f"Tiếp tục duy trì và phát triển thêm độ sâu nội dung, đặc biệt ở "
                    f"những phần có điểm accuracy thấp (hiện tại {sig['accuracy']:.2f}/1.0) "
                    f"để nâng cao tính thuyết phục."
                )
                suggestions.append(
                    f"Tăng cường liên kết giữa các ý bằng các câu chuyển tiếp rõ ràng, "
                    f"giúp bài trình bày mạch lạc hơn."
                )
            elif norm >= 0.4:
                suggestions.append(
                    f"Tái cấu trúc nội dung để bám sát mục tiêu học tập: điểm relevance hiện tại "
                    f"chỉ {sig['relevance']:.2f}/1.0, cần tập trung vào những yêu cầu cốt lõi "
                    f"của đề tài thay vì nói chung chung."
                )
                if sig["semantic"] < 0.6:
                    suggestions.append(
                        f"Cải thiện tính mạch lạc của bài trình bày: điểm semantic "
                        f"{sig['semantic']:.2f}/1.0 cho thấy các đoạn trình bày còn rời rạc, "
                        f"thiếu luồng ý liên kết. Sử dụng cấu trúc câu chuyện hoặc logic "
                        f"để dẫn dắt người nghe."
                    )
                suggestions.append(
                    f"Bổ sung ví dụ thực tế hoặc tình huống giả định (case study) để minh họa "
                    f"cho các khái niệm trừu tượng, giúp người nghe dễ hiểu và ghi nhớ hơn."
                )
            else:
                suggestions.append(
                    f"Nghiên cứu lại đề tài một cách hệ thống: xác định rõ 3-5 điểm chính "
                    f"cần trình bày và xây dựng nội dung xung quanh chúng. Điểm relevance "
                    f"{sig['relevance']:.2f}/1.0 và semantic {sig['semantic']:.2f}/1.0 cho thấy "
                    f"bài trình bày chưa bám sát mục tiêu."
                )
                if sig["depth"] > 0 and sig["depth"] < 0.5:
                    suggestions.append(
                        f"Tăng cường độ sâu của nội dung kỹ thuật, tránh nói chung chung "
                        f"về nguyên lý mà thiếu chi tiết triển khai cụ thể "
                        f"(điểm depth hiện tại {sig['depth']:.2f}/1.0)."
                    )
                suggestions.append(
                    f"Sử dụng nguồn tài liệu đáng tin cậy (bài báo khoa học, tài liệu chính thống) "
                    f"để củng cố các luận điểm chính, tránh thông tin chưa được kiểm chứng."
                )

        # ── Slide Quality ────────────────────────────────────────
        elif any(k in n for k in ("slide", "powerpoint", "trang chiếu", "visuals", "hình ảnh")):
            if norm >= 0.7:
                suggestions.append(
                    f"Giữ vững phong cách thiết kế slide hiện tại, đảm bảo mỗi slide có "
                    f"đúng một thông điệp chính và dễ đọc trong 3-5 giây đầu."
                )
                suggestions.append(
                    f"Tối ưu thêm alignment giữa slide và audio: kiểm tra điểm "
                    f"{sig['alignment']:.2f}/1.0 và đảm bảo nội dung trên slide khớp "
                    f"với những gì đang nói tại thời điểm đó."
                )
            elif norm >= 0.4:
                slide_hint = (
                    "Giảm số lượng slide và tập trung vào các ý chính, "
                    "sử dụng biểu đồ hoặc sơ đồ"
                    if sig["seg_count"] > 20
                    else "Cải thiện bố cục slide"
                )
                suggestions.append(
                    f"{slide_hint} thay vì nhiều chữ. "
                    f"Điểm alignment hiện tại {sig['alignment']:.2f}/1.0."
                )
                suggestions.append(
                    f"Thiết kế lại slide để làm nổi bật các khái niệm cốt lõi bằng "
                    f"hình ảnh, biểu đồ, hoặc bảng so sánh trực quan "
                    f"thay vì dùng quá nhiều bullet points."
                )
                suggestions.append(
                    f"Đảm bảo mỗi slide đều có thông điệp chính liên kết trực tiếp "
                    f"với nội dung đang trình bày tại thời điểm đó, "
                    f"giúp tăng điểm alignment lên mức 0.7+."
                )
            else:
                suggestions.append(
                    f"Thiết kế lại toàn bộ slide từ đầu: giảm tối đa chữ trên slide "
                    f"(mỗi slide tối đa 6 dòng, mỗi dòng tối đa 6 từ), "
                    f"dùng nhiều hình ảnh, sơ đồ và biểu đồ để truyền tải thông tin. "
                    f"Điểm alignment {sig['alignment']:.2f}/1.0 cho thấy slide hiện tại "
                    f"chưa đồng bộ với nội dung audio."
                )
                suggestions.append(
                    f"Tạo template slide đồng bộ cho toàn bộ bài trình bày: "
                    f"dùng cùng một bảng màu, font chữ và kiểu bố cục để tạo "
                    f"sự chuyên nghiệp và giúp khán giả dễ theo dõi."
                )
                suggestions.append(
                    f"Rà soát lại nội dung trên từng slide để đảm bảo ngắn gọn, súc tích, "
                    f"và dễ đọc. Mỗi slide nên trả lời được một câu hỏi "
                    f"hoặc truyền tải một thông điệp rõ ràng."
                )

        # ── Voice Quality ────────────────────────────────────────
        elif any(k in n for k in ("voice", "speech", "giọng", "delivery", "oral")):
            if not sig["has_sq_data"]:
                suggestions.append(
                    f"Đảm bảo thiết bị ghi âm hoạt động tốt và thu âm trong môi trường yên tĩnh "
                    f"cho các lần thuyết trình sau để có dữ liệu giọng nói phục vụ đánh giá."
                )
                suggestions.append(
                    f"Luyện tập kỹ năng điều chỉnh giọng nói: nhấn mạnh từ khóa, "
                    f"nghỉ đúng chỗ, tránh filler words (ừm, ạ, vâng) để tạo ấn tượng chuyên nghiệp."
                )
                suggestions.append(
                    f"Thực hành thuyết trình trước gương hoặc ghi âm lại để tự nghe và "
                    f"điều chỉnh ngữ điệu, tốc độ phù hợp với nội dung trình bày."
                )
            elif norm >= 0.7:
                suggestions.append(
                    f"Tiếp tục duy trì phong cách trình bày hiện tại: "
                    f"trôi chảy ({sig['fluency']:.2f}/1.0), "
                    f"phát âm rõ ({sig['clarity']:.2f}/1.0), "
                    f"tự tin ({sig['confidence']:.2f}/1.0)."
                )
                suggestions.append(
                    f"Tập thêm ngữ điệu nhấn mạnh ở những ý quan trọng để tăng sức thuyết phục."
                )
                suggestions.append(
                    f"Thử thêm câu hỏi dẫn dắt hoặc tạm dừng có chủ đích (dramatic pause) "
                    f"để khán giả có thời gian tiếp thu thông tin."
                )
            elif norm >= 0.4:
                fs_note = f"điểm fluency {sig['fluency']:.2f}/1.0" if sig['fluency'] > 0 else "chưa có dữ liệu fluency"
                suggestions.append(
                    f"Tập trung cải thiện sự trôi chảy: {fs_note}, "
                    f"{'cần giảm ngắt quãng và filler words bằng cách luyện tập trước gương nhiều hơn' if sig['fluency'] < 0.6 else 'trôi chảy ở mức trung bình, cần ổn định hơn'}."
                )
                if sig["clarity"] < 0.6:
                    suggestions.append(
                        f"Cải thiện độ rõ của giọng nói: phát âm từng từ rõ ràng hơn, "
                        f"điểm clarity hiện tại chỉ {sig['clarity']:.2f}/1.0. "
                        f"{'Giọng nói quá nhanh hoặc quá chậm đều ảnh hưởng đến sự tiếp thu.' if sig['speaking_rate'] > 0 else 'Chú ý tốc độ nói vừa phải.'}"
                    )
                # Speaking rate feedback
                if sig["speaking_rate"] > 0:
                    sr = sig["speaking_rate"]
                    if sr < 100:
                        suggestions.append(
                            f"Tăng tốc độ nói: hiện tại {sr:.0f} syllables/min — hơi chậm, "
                            f"nên đạt khoảng 120-150 syllables/min để giữ sự chú ý của khán giả."
                        )
                    elif sr > 180:
                        suggestions.append(
                            f"Giảm tốc độ nói: hiện tại {sr:.0f} syllables/min — khá nhanh, "
                            f"nên chậm lại khoảng 120-150 syllables/min để khán giả dễ theo dõi."
                        )
                suggestions.append(
                    f"Tăng sự tự tin khi trình bày: điểm confidence {sig['confidence']:.2f}/1.0. "
                    f"Sử dụng ngôn ngữ cơ thể (tư thế, ánh mắt) để tự tin hơn khi đứng trước khán giả."
                )
            else:
                suggestions.append(
                    f"Ưu tiên luyện tập toàn bộ bài trình bày ít nhất 3-5 lần trước khi thuyết trình chính thức. "
                    f"Hiện tại: fluency {sig['fluency']:.2f}/1.0, clarity {sig['clarity']:.2f}/1.0, "
                    f"confidence {sig['confidence']:.2f}/1.0 — tất cả đều cần được cải thiện đáng kể."
                )
                if sig["hesitation"] > 3 or sig["hesitation_time"] > 5:
                    suggestions.append(
                        f"Giảm số lần ngập ngừng: hiện tại ghi nhận {sig['hesitation']} lần hesitation "
                        f"(tổng {sig['hesitation_time']:.1f}s, tỉ lệ {sig['hesitation_rate']:.1f} lần/phút). "
                        f"Sử dụng kỹ thuật 'pausing' có chủ đích (nghỉ 2-3 giây giữa các ý) "
                        f"thay vì 'um', 'uh' để tạo sự chuyên nghiệp."
                    )
                if sig["speech_rhythm"] < 0.5:
                    suggestions.append(
                        f"Cải thiện nhịp điệu speech: điểm hiện tại {sig['speech_rhythm']:.2f}/1.0. "
                        f"Thực hành thay đổi tốc độ và cao độ phù hợp với nội dung — nhanh khi hào hứng, "
                        f"chậm khi nhấn mạnh điểm quan trọng."
                    )
                suggestions.append(
                    f"Ghi âm lại bài trình bày và tự nghe lại để nhận diện những điểm yếu "
                    f"về giọng nói cần cải thiện, sau đó tập trung sửa từng điểm đó."
                )

        # ── Structure / Organization ──────────────────────────────
        elif any(k in n for k in ("structure", "organization", "cấu trúc", "logical")):
            if norm >= 0.7:
                suggestions.append("Giữ vững cấu trúc hiện tại, đảm bảo mỗi phần đều có mục đích rõ ràng.")
            elif norm >= 0.4:
                suggestions.append(
                    f"Cải thiện luồng bài: mở đầu rõ ràng với overview, phát triển có trọng tâm, "
                    f"kết luận mạnh. Sử dụng các cụm từ chuyển tiếp (Transition) để liên kết các phần."
                )
                suggestions.append(
                    f"Áp dụng mô hình PREP (Point-Reason-Example-Point) hoặc STAR "
                    f"(Situation-Task-Action-Result) cho từng phần trình bày để tăng tính logic."
                )
            else:
                suggestions.append(
                    f"Tái cấu trúc toàn bộ bài: xác định rõ 3-5 phần chính và đảm bảo "
                    f"có luồng logic xuyên suốt từ đầu đến cuối. "
                    f"Điểm overall {sig['overall']:.2f}/1.0 cho thấy bài trình bày thiếu sự liên kết."
                )
                suggestions.append(
                    f"Dùng các cụm từ chuyển tiếp rõ ràng ('Tiếp theo', 'Bên cạnh đó', 'Do đó') "
                    f"để dẫn dắt người nghe qua từng phần."
                )

        # ── Engagement ───────────────────────────────────────────
        elif any(k in n for k in ("engagement", "tương tác", "interest", "hứng thú")):
            if norm >= 0.7:
                suggestions.append("Phát huy phong cách thu hút khán giả hiện tại, thử thêm các hoạt động tương tác mới.")
            elif norm >= 0.4:
                suggestions.append(
                    f"Thêm câu hỏi dẫn dắt ('Các bạn có thấy điều này giống nhau không?'), "
                    f"câu chuyện thực tế hoặc ví dụ gần gũi để tăng sự chú ý của khán giả."
                )
                suggestions.append(
                    f"Sử dụng ngữ điệu và cử chỉ tay để duy trì sự hứng thú xuyên suốt bài trình bày."
                )
            else:
                suggestions.append(
                    f"Tạo điểm nhấn (highlight) xuyên suốt bài trình bày: câu chuyện thực tế, "
                    f"số liệu bất ngờ, hoặc câu hỏi kích thích tư duy để khán giả không bị mất tập trung."
                )
                suggestions.append(
                    f"Sử dụng ngữ điệu có高低 (giọng lên xuống), tốc độ thay đổi, "
                    f"và tạm dừng có chủ đích để duy trì sự hứng thú."
                )

        # ── Generic ──────────────────────────────────────────────
        if not suggestions:
            if norm >= 0.7:
                suggestions.append(
                    f"Tiêu chí '{criteria_name}' đạt mức khá ({score:.1f}/{max_score:.0f}). "
                    f"Cần duy trì và phát huy thêm."
                )
            elif norm >= 0.4:
                suggestions.append(
                    f"Cần cải thiện tiêu chí '{criteria_name}' (hiện tại {score:.1f}/{max_score:.0f}) "
                    f"để nâng cao điểm tổng kết. Tham khảo rubric chi tiết của lớp."
                )
            else:
                suggestions.append(
                    f"Tiêu chí '{criteria_name}' cần được ưu tiên cải thiện ngay "
                    f"(hiện tại {score:.1f}/{max_score:.0f}). Tham khảo rubric và đối chiếu "
                    f"với bài trình bày thực tế để xác định điểm cần sửa."
                )

        return suggestions[:3]

    def _calculate_rubric_scores_fallback(
        self,
        segment_analyses: List[Dict],
        overall_scores: Dict,
        speech_quality: Dict,
        analysis_results: Dict = None,
        rubric_criteria: List[Dict] = None,
        speaker_analyses: Dict = None
    ) -> Dict[str, Any]:
        """Fallback calculation if AI fails"""
        logger.info("🔄 Using fallback rubric scoring...")
        
        criterion_scores = {}
        
        if rubric_criteria:
            for criterion in rubric_criteria:
                criteria_id = ReportAnalysisService._rubric_row_id(criterion)
                if criteria_id is None:
                    logger.warning("Skipping rubric row without criteriaId / classRubricCriteriaId")
                    continue
                criteria_name = criterion.get('criteriaName', criterion.get('criteria_name', 'Unknown'))
                max_score = float(criterion.get('maxScore') or 100)
                weight = float(criterion.get('weight') or 0)
                factor = self._heuristic_score_factor(criteria_name, overall_scores, speech_quality)
                score = round(factor * max_score, 2)
                try:
                    cid_val = int(criteria_id)
                except (TypeError, ValueError):
                    cid_val = criteria_id

                criterion_scores[str(criteria_id)] = {
                    'criteriaId': cid_val,
                    'criteriaName': criteria_name,
                    'score': score,
                    'maxScore': max_score,
                    'weight': weight,
                    'comment': self._build_fallback_comment(
                        criteria_name, score, max_score, speech_quality,
                        overall_scores, segment_analyses, analysis_results,
                        speaker_analyses
                    ),
                    'suggestions': self._build_fallback_suggestions(
                        criteria_name, score, max_score, speech_quality,
                        overall_scores, segment_analyses, analysis_results,
                    ),
                }
        
        weighted = self._weighted_overall_from_criteria(criterion_scores)
        base_os = dict(overall_scores or {})
        base_os['overallScore'] = weighted
        base_os['rubricBased'] = True

        report_content = self._build_vietnamese_report_summary(
            weighted,
            criterion_scores,
            base_os,
            rubric_criteria,
            speech_quality,
        )

        return {
            'criterion_scores': criterion_scores,
            'report_content': report_content,
            'overall_scores': base_os,
            'reportBody': {},
        }


# ============================================================
# Helper class for teamwork results
# ============================================================

class TeamworkAnalysisResult:
    """Result of teamwork analysis"""
    def __init__(
        self,
        participation_balance: Dict[str, Any],
        speaker_transitions: Dict[str, Any],
        topic_continuity: Dict[str, Any],
        overall_teamwork_score: float,
        feedback: str
    ):
        self.participation_balance = participation_balance
        self.speaker_transitions = speaker_transitions
        self.topic_continuity = topic_continuity
        self.overall_teamwork_score = overall_teamwork_score
        self.feedback = feedback


# Singleton instance
_report_analysis_service = None

def get_report_analysis_service(db_service: DatabaseService = None) -> 'ReportAnalysisService':
    """Get report analysis service singleton"""
    global _report_analysis_service
    if _report_analysis_service is None:
        if db_service is None:
            db_service = get_database_service()
        _report_analysis_service = ReportAnalysisService(db_service)
    return _report_analysis_service
