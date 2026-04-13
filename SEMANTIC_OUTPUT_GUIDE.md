# 📊 Report Worker — Hướng Dẫn Sử Dụng Output Từ Semantic Worker

> Tài liệu này tóm tắt toàn bộ dữ liệu mà **semantic worker** phân tích và lưu vào DB.  
> Report worker cần đọc đúng các bảng, hiểu đúng ý nghĩa từng field để tạo AI report chính xác.

---

## 1. Flow Dữ Liệu Tổng Quan

```
ASR Worker
  └─ Transcript segments + diarization (SPEAKER_00, SPEAKER_01...)
        ↓
Semantic Worker phân tích:
  ├─ Content Relevance   → so sánh đoạn nói vs topic
  ├─ Semantic Similarity → so sánh đoạn nói vs slide content
  ├─ Slide Alignment     → đúng thứ tự slide không
  └─ Speech Quality      → hesitation, clarity, fluency...
        ↓ lưu vào DB
┌──────────────────────────────────────────────┐
│  SegmentAnalyses      (1 row / segment)       │
│  ContentRelevance     (1 row / segment)       │
│  SemanticSimilarity   (1 row / segment)       │
│  AlignmentChecks      (1 row / segment)       │
│  SpeechQualityAnalysis (1 row / presentation) │
│  SegmentSpeechQuality  (1 row / segment)      │
│  HesitationPatterns    (N rows / presentation)│
│  AnalysisResults       (1 row / presentation) │
└──────────────────────────────────────────────┘
        ↓
Report Worker đọc DB → LLM Prompt → AI Report
```

---

## 2. Bảng `SegmentAnalyses` — Phân tích mỗi đoạn nói

> **Join path:** `SegmentAnalyses sa JOIN TranscriptSegments ts ON sa.segmentId = ts.segmentId JOIN Transcripts t ON ts.transcriptId = t.transcriptId WHERE t.presentationId = ?`

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện | Lưu ý |
|-------|------|---------|-----|--------------|-------|
| `segmentId` | INT | FK tới `TranscriptSegments` | — | — | — |
| `speakerLabel` | VARCHAR(50) | Label từ diarization (`SPEAKER_00`, `SPEAKER_01`...) | — | — | NULL nếu không có diarization |
| `relevanceScore` | FLOAT | ~~Độ khớp đoạn nói vs chủ đề (topic)~~ **Raw embedding similarity only — KHÔNG dùng để đánh giá content** | — | — | 🚫 Không đưa vào overallScore. LLM của report-worker tự đánh giá. |
| `semanticScore` | FLOAT | **Độ khớp đoạn nói vs slide content** | ≥ 0.5 | < 0.25 | 0.0–1.0, contrastive-normalised |
| `alignmentScore` | FLOAT | **Đúng thứ tự slide không** | ≥ 0.6 | < 0.3 | 35% timing + 65% content match |
| `bestMatchingSlide` | INT | Virtual page slide khớp nhất | — | — | Từ PDF expansion |
| `expectedSlideNumber` | INT | Slide kỳ vọng theo tiến độ thời gian | — | — | Dùng để tính alignment |
| `timingDeviation` | FLOAT | Độ lệch thời gian (giây) | ≈ 0 | > 30s | Dương = nói trễ slide |
| `issues` | JSON | Danh sách vấn đề phát hiện | `[]` | Nhiều mục | Array of strings |
| `suggestions` | JSON | Gợi ý cải thiện tương ứng | — | — | Array of strings |
| `topicKeywordsFound` | JSON | Keywords topic xuất hiện trong đoạn nói | Nhiều | `[]` | Tham khảo, không dùng để chấm điểm |

**Aggregate per-speaker:**
```sql
SELECT speakerLabel,
  COUNT(*) as segmentCount,
  -- Không dùng AVG(relevanceScore) vì không đánh giá content quality
  AVG(semanticScore) as avgSemantic,
  AVG(alignmentScore) as avgAlignment
FROM SegmentAnalyses sa
JOIN TranscriptSegments ts ON sa.segmentId = ts.segmentId
JOIN Transcripts t ON ts.transcriptId = t.transcriptId
WHERE t.presentationId = ? GROUP BY speakerLabel
```

> [!IMPORTANT]
> **`relevanceScore` KHÔNG được dùng để tính điểm tổng**. Đây là raw cosine similarity giữa embedding đoạn nói và embedding tên topic. Metric này **không có khả năng đánh giá được** người nói có thực sự bám sát nội dung chủ đề không. Ví dụ: topic "PYTHON BASIC 4" + câu nói bất kỳ bằng tiếng Việt sẽ cho score 0.7–0.8 do baseline inflation của multilingual embedding.
>
> **Content quality phải do LLM của report-worker tự đánh giá bằng cách đọc transcript thật.**

---

## 3. Bảng `ContentRelevance` — Chi tiết relevance

> **Join:** `LEFT JOIN ContentRelevance cr ON sa.segAnalysisId = cr.segAnalysisId`

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện |
|-------|------|---------|-----|--------------|
| `relevanceScore` | FLOAT | Copy từ SegmentAnalyses.relevanceScore | ≥ 0.6 | < 0.4 |
| `matchedConcepts` | TEXT | Keywords topic tìm thấy (join bằng ", ") | Nhiều | rỗng/NULL |
| `explanation` | TEXT | Issues phát hiện (join bằng "; ") | NULL/rỗng | Nhiều issue |

---

## 4. Bảng `SemanticSimilarity` — Chi tiết similarity

> **Join:** `LEFT JOIN SemanticSimilarity ss ON sa.segAnalysisId = ss.segAnalysisId`

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện |
|-------|------|---------|-----|--------------|
| `similarityScore` | FLOAT | Cosine similarity (contrastive-normalised) | ≥ 0.5 | < 0.2 |

**Giải thích contrastive normalization:**
- Raw cosine similarity với cùng ngôn ngữ tiếng Việt thường baseline ≈ 0.55–0.75 dù nội dung không liên quan
- Sau normalize: score ≈ 0 khi tất cả slides đều "lạ", score cao chỉ khi 1 slide rõ ràng khớp
- **Đừng nhầm 0.3 là thấp** — score 0.3 sau normalize = "có liên quan hơn mức trung bình đáng kể"

---

## 5. Bảng `AlignmentChecks` — Chi tiết alignment

> **Join:** `LEFT JOIN AlignmentChecks ac ON sa.segAnalysisId = ac.segAnalysisId`

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện |
|-------|------|---------|-----|--------------|
| `alignmentStatus` | ENUM | `"aligned"` hoặc `"misaligned"` | `"aligned"` | `"misaligned"` |
| `timingSyncScore` | FLOAT | = alignmentScore (0.0–1.0) | ≥ 0.6 | < 0.3 |
| `expectedSlideNumber` | INT | Slide kỳ vọng theo thời gian | — | — |
| `misalignmentReason` | TEXT | Lý do lệch (vd: `"Timing deviation: 12.3s"`) | NULL | Có giá trị |

**Công thức alignment score:**
```
alignmentScore = 0.35 × temporal_score + 0.65 × content_match_score

temporal_score  = 1 - |expected_progress - actual_progress| × 2
content_match   = cosine(segment, expected_slide_text), baseline-corrected ở 0.55
```
→ Người nói đúng chủ đề slide tại đúng thời điểm → cao; nói lạc đề → score < 0.35

---

## 6. Bảng `SpeechQualityAnalysis` — Chất lượng giọng tổng thể

> **Query:** `SELECT * FROM SpeechQualityAnalysis WHERE presentationId = ?` — **1 row**

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện | Ghi chú |
|-------|------|---------|-----|--------------|---------|
| `fluencyScore` | FLOAT | Độ trôi chảy, ít do dự | ≥ 0.6 | < 0.3 | `0.0` = cực kỳ nhiều filler |
| `clarityScore` | FLOAT | Độ rõ ràng giọng nói | ≥ 0.7 | < 0.5 | |
| `confidenceScore` | FLOAT | Mức tự tin qua pitch/energy | ≥ 0.6 | < 0.4 | |
| `overallScore` | FLOAT | Weighted avg các score trên | ≥ 0.6 | < 0.4 | |
| `speakingRate` | FLOAT | Tốc độ nói (words/minute) | 120–160 | < 80 hoặc > 200 | |
| `pitchVariation` | FLOAT | Biến thiên pitch 0–1 | 0.3–0.7 | < 0.1 | < 0.1 = đơn điệu |
| `volumeVariation` | FLOAT | Biến thiên âm lượng 0–1 | 0.3–0.7 | < 0.1 | < 0.1 = đơn điệu |
| `speechRhythmScore` | FLOAT | Điểm nhịp điệu nói | ≥ 0.5 | < 0.3 | |
| `silenceRatio` | FLOAT | % thời gian im lặng | 0.10–0.25 | > 0.40 | > 0.4 = quá nhiều pause |
| `voicedRatio` | FLOAT | % thời gian có giọng | 0.75–0.90 | < 0.50 | |
| `audioDuration` | FLOAT | Tổng thời gian audio (giây) | — | — | |
| `mfccFeatures` | JSON | 13 MFCC coefficients | — | — | **Không dùng trong LLM prompt** |
| `pitchMean` | FLOAT | Tần số giọng TB (Hz) | — | — | Kỹ thuật, reference only |
| `energyMean` | FLOAT | Năng lượng âm TB | — | — | Kỹ thuật, reference only |

---

## 7. Bảng `SegmentSpeechQuality` — Chất lượng giọng mỗi segment

> **Join:** `LEFT JOIN SegmentSpeechQuality sq ON sq.segmentId = sa.segmentId`

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện |
|-------|------|---------|-----|--------------|
| `segmentHesitationCount` | INT | Số lần do dự / filler trong đoạn | 0–2 | > 5 |
| `segmentHesitationTime` | FLOAT | Tổng thời gian do dự (giây) | < 2s | > 10s |
| `qualityIssues` | JSON | Issues speech trong đoạn | `[]` | Nhiều mục |
| `qualitySuggestions` | JSON | Gợi ý cải thiện giọng | — | — |

> ⚠️ **Data trước 2026-04-13** có `segmentHesitationCount = 0` do bug key mismatch. Cần rerun.

---

## 8. Bảng `HesitationPatterns` — Từng lần do dự

> **Join:** `LEFT JOIN HesitationPatterns hp ON hp.speechAnalysisId = sqa.id`  
> 1 presentation → vài chục đến hàng trăm patterns

| Field | Kiểu | Ý nghĩa | Tốt | Cần cải thiện |
|-------|------|---------|-----|--------------|
| `duration` | FLOAT | Độ dài do dự (giây) | < 0.5s | > 2s |
| `patternType` | VARCHAR | `"uh"`, `"um"`, `"silence"`, `"repetition"` | — | — |
| `confidence` | FLOAT | Độ chắc chắn detection | ≥ 0.7 | < 0.5 |

**Dùng trong report:** `COUNT(*)` và `SUM(duration)` cho tổng số lần và tổng thời gian do dự.

---

## 9. Bảng `AnalysisResults` — Overall score

| Field | Kiểu | Ý nghĩa |
|-------|------|---------|
| `overallScore` | FLOAT | 0.0–1.0, weighted avg tất cả dimensions |
| `status` | ENUM | `"done"` khi semantic hoàn thành |

---

## 10. Bảng `Speakers` — Thông tin diarization

| Field | Kiểu | Ý nghĩa |
|-------|------|---------|
| `aiSpeakerLabel` | VARCHAR | `SPEAKER_00`, `SPEAKER_01`... |
| `studentId` | INT | Liên kết student thật (NULL nếu chưa map) |
| `isMapped` | BOOL | Giáo viên đã map chưa |
| `totalDurationSeconds` | FLOAT | Tổng thời gian speaker nói |
| `segmentCount` | INT | Số đoạn nói |

---

## 11. ⚠️ Phân chia Trách Nhiệm — Rất Quan Trọng

### Semantic Worker làm gì

Semantic worker chỉ chịu trách nhiệm **phân tích kỹ thuật cấu trúc**:

| Metric | Semantic Worker | Report Worker (LLM) |
|--------|----------------|--------------------|
| Slide content match (embedding) | ✅ Làm | ❌ Không làm |
| Slide ordering alignment | ✅ Làm | ❌ Không làm |
| Hesitation detection (audio) | ✅ Làm | ❌ Không làm |
| Speech quality (fluency, clarity) | ✅ Làm | ❌ Không làm |
| **Content relevance to topic** | 🚫 Raw data ONLY | ✅ **LLM tự đánh giá** |
| Content quality & depth | ❌ Không làm | ✅ LLM tự đánh giá |
| Narrative coherence | ❌ Không làm | ✅ LLM tự đánh giá |
| Rubric-based scoring | ❌ Không làm | ✅ LLM tự đánh giá |

### overallScore từ Semantic Worker

```
overallScore = 0.5 × semanticScore + 0.5 × alignmentScore
             + 0.3 × speechQualityScore (nếu có)

⚠️ contentRelevance (relevanceScore) KHÔNG có trong công thức này.
```

Score này chỉ phản ánh **quality kỹ thuật về presentation structure**, không phản ánh content quality.

### Report Worker (LLM) phải tự làm

Khi LLM nhận được data từ DB, cần:
1. Đọc `segmentText` của từng segment (transcript thật)
2. Đọc `topicName`, `topicDescription`, `topicRequirements` từ DB
3. Tự đánh giá: người nói có bám sát chủ đề không? Nội dung có đúng không?
4. Kết hợp với `rubricData` để chấm từng criteria
5. KHÔNG tin tưởng `relevanceScore` từ semantic worker để đánh giá content

---

## 12. Query Đầy Đủ Cho Per-Speaker Analysis

```sql
SELECT
  sa.segmentId,
  sa.speakerLabel,
  sa.relevanceScore,
  sa.semanticScore,
  sa.alignmentScore,
  sa.issues,
  sa.suggestions,
  sa.topicKeywordsFound,
  ts.segmentText,
  ts.startTimestamp,
  ts.endTimestamp,
  sq.segmentHesitationCount,
  sq.segmentHesitationTime,
  sq.qualityIssues,
  sp.totalDurationSeconds    AS speakerTotalDuration,
  sp.segmentCount            AS speakerSegmentCount,
  sp.isMapped,
  sp.studentId
FROM SegmentAnalyses sa
JOIN TranscriptSegments ts ON sa.segmentId = ts.segmentId
JOIN Transcripts t         ON ts.transcriptId = t.transcriptId
LEFT JOIN SegmentSpeechQuality sq ON sq.segmentId = sa.segmentId
LEFT JOIN Speakers sp ON sp.aiSpeakerLabel = sa.speakerLabel
                      AND sp.presentationId = t.presentationId
WHERE t.presentationId = %s
ORDER BY ts.segmentNumber ASC
```

---

## 13. Mapping Score → Nhận Xét Cho LLM

> [!NOTE]
> Bảng này chỉ áp dụng cho `semanticScore`, `alignmentScore`, và speech quality scores.
> KHÔNG áp dụng cho `relevanceScore` (không đáng tin cậy).

| Score | Nhận xét (tiếng Việt cho LLM) |
|-------|-------------------------------|
| 0.80–1.00 | Xuất sắc, đáng khen ngợi |
| 0.60–0.80 | Tốt, đáp ứng yêu cầu |
| 0.40–0.60 | Trung bình, cần cải thiện nhẹ |
| 0.20–0.40 | Yếu, cần cải thiện đáng kể |
| 0.00–0.20 | Rất yếu, không đáp ứng yêu cầu |

---

## 14. Checklist Trước Khi Chạy Report Worker

- [ ] `SegmentAnalyses.speakerLabel` có data (presentation rerun sau migration 2026-04-13)
- [ ] `SegmentSpeechQuality.segmentHesitationCount > 0` (presentation rerun sau fix 2026-04-13)
- [ ] `AnalysisResults.status = "done"` cho presentation này
- [ ] `Speakers` có ≥ 1 row cho presentation này
- [ ] `SpeechQualityAnalysis` có row cho presentation này

---

## 15. Fields KHÔNG Đưa Vào LLM Prompt

| Field | Lý do |
|-------|-------|
| `mfccFeatures` | Raw audio coefficients, không có ý nghĩa ngữ văn |
| `pitchMean`, `pitchStd` | Giá trị Hz kỹ thuật |
| `energyMean`, `energyStd` | Kỹ thuật |
| `startTime`/`endTime` của hesitation | Chi tiết quá, dùng aggregate |
| `processingTime` | Debug info |
| `confidence` của hesitation | Internal scoring |
| **`relevanceScore`** | ❌ Không đáng tin cậy — LLM tự đánh giá content từ transcript thật |

**✅ Nên dùng:** Aggregated counts, averages của `semanticScore` + `alignmentScore`, speech quality scores, `segmentText` (transcript thật để LLM đọc), `issues`/`suggestions` arrays.
