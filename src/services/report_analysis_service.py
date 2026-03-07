"""
Report Analysis Service - Core logic for analyzing presentation segments

This service analyzes each transcript segment against slides and topic,
calculating scores and generating issues/suggestions using AI (OpenAI or Gemini).
"""

import json
import re
from typing import List, Dict, Any, Tuple
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
from src.utils.exceptions import AnalysisError

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
                    max_tokens=4000
                )
                return response.choices[0].message.content
                
            elif self.ai_provider == 'gemini':
                response = self.gemini_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return response.text
                
        except Exception as e:
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
                topic_keywords_found=result.get('topic_keywords_found', topic_keywords[:5])
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
            topic_keywords_found=keywords_found
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
        for seg in segment_analyses:
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

        from collections import Counter
        top_issues = Counter(all_issues).most_common(5)
        top_suggestions = Counter(all_suggestions).most_common(5)

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

Các vấn đề phổ biến nhất:
{chr(10).join([f"- {issue[0]}" for issue in top_issues])}

Các đề xuất cải thiện phổ biến nhất:
{chr(10).join([f"- {suggestion[0]}" for suggestion in top_suggestions])}

Hãy trả về JSON với các trường sau (KHÔNG có markdown, KHÔNG có giải thích):
{{
  "rating": <điểm đánh giá từ 1-5>,
  "comments": "<đoạn feedback tổng quan bằng tiếng Việt, khoảng 500-700 từ, xuống dòng rõ ràng>"
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
