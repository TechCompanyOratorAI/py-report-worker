# py-report-worker
Report Worker - Worker phân tích và tạo báo cáo cho presentation
## Chức năng
Worker này thực hiện:
1. Nhận job từ AWS SQS queue
2. Đọc dữ liệu presentation từ database (Transcripts, TranscriptSegments, Slides)
3. Phân tích từng segment:
   - Tính relevanceScore (độ liên quan topic)
   - Tính semanticScore (so khớp với slide)
   - Tính alignmentScore (căn chỉnh thời gian)
   - Xác định bestMatchingSlide, expectedSlideNumber, timingDeviation
   - Tạo issues và suggestions
4. Lưu kết quả vào database:
   - **SegmentAnalyses** - kết quả chi tiết từng segment
   - **AnalysisResults** - kết quả tổng kết toàn presentation
5. Gửi webhook về API
## Cấu hình Environment Variables
Tạo file `.env` trong thư mục root của worker với nội dung sau:
```bash
# =======================
# Worker Configuration
# =======================
WORKER_ID=report-worker-1
POLL_INTERVAL=5
MAX_MESSAGES=1
WAIT_TIME_SECONDS=20

# =======================
# AWS Configuration
# =======================
AWS_REGION=ap-southeast-1
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_SQS_REPORT_QUEUE_URL=https://sqs.ap-southeast-1.amazonaws.com/your-account-id/report-queue

# =======================
# Database Configuration (MySQL)
# =======================
DB_HOST=localhost
DB_PORT=3306
DB_NAME=OratorAI
DB_USERNAME=your_db_user
DB_PASSWORD=your_db_password
DB_SSL=true

# =======================
# Webhook Configuration
# =======================
WEBHOOK_BASE_URL=http://localhost:3000
WEBHOOK_SECRET=your_webhook_secret_here

# =======================
# Analysis Configuration
# =======================
SIMILARITY_THRESHOLD=0.5
RELEVANCE_THRESHOLD=0.5
ALIGNMENT_THRESHOLD=0.5

# =======================
# Logging Configuration
# =======================
LOG_LEVEL=INFO
```

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy Worker

```bash
python main.py
```

## Database Tables

Worker ghi dữ liệu vào 2 bảng:

### SegmentAnalyses
| Field | Type | Description |
|-------|------|-------------|
| segAnalysisId | INT (PK, AUTO_INCREMENT) | ID của bản ghi phân tích |
| segmentId | INT (FK) | ID của segment trong TranscriptSegments |
| slideId | INT (FK) | ID của slide phù hợp nhất |
| configId | NULL | Reserved |
| analyzedAt | DATETIME | Thời điểm phân tích |
| relevanceScore | FLOAT(0.0-1.0) | Điểm liên quan nội dung |
| semanticScore | FLOAT(0.0-1.0) | Điểm tương đồng ngữ nghĩa |
| alignmentScore | FLOAT(0.0-1.0) | Điểm căn chỉnh thời gian |
| bestMatchingSlide | INT | Số slide phù hợp nhất |
| expectedSlideNumber | INT | Slide dự kiến theo timing |
| timingDeviation | FLOAT | Độ lệch thời gian |
| issues | JSON | Các vấn đề phát hiện |
| suggestions | JSON | Đề xuất cải thiện |
| topicKeywordsFound | tìm thấy |

### JSON | Keywords AnalysisResults
| Field | Type | Description |
|-------|------|-------------|
| resultId | INT (PK, AUTO_INCREMENT) | ID của kết quả |
| presentationId | INT (FK, UNIQUE) | ID của presentation |
| configId | NULL | Reserved |
| overallScore | FLOAT | Điểm tổng thể |
| analyzedAt | DATETIME | Thời điểm phân tích |
| status | VARCHAR | Trạng thái ('done') |
