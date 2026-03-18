"""
FastAPI Application - AI Report API

Provides endpoints to get AI report data
"""

import sys
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add src to path
sys.path.insert(0, 'src')

from config.settings import settings
from utils.logger import get_logger
from utils.exceptions import DatabaseError
from services.database_service import get_database_service

logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="AI Report Worker API",
    description="API for retrieving AI report data",
    version="1.0.0"
)


# Response models
class AIReportResponse(BaseModel):
    reportId: Optional[int]
    presentationId: int
    overallScore: Optional[float]
    criterionScores: Optional[dict]
    reportContent: Optional[str]
    reportStatus: Optional[str]
    generatedByModel: Optional[str]
    generatedAt: Optional[str]


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# Exception handlers
@app.exception_handler(DatabaseError)
async def database_error_handler(request, exc: DatabaseError):
    return JSONResponse(
        status_code=500,
        content={"error": "Database error", "detail": str(exc)}
    )


@app.exception_handler(Exception)
async def general_error_handler(request, exc: Exception):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ai-report-worker-api"}


# AI Report endpoints
@app.get(
    "/api/v1/reports/submission/{submission_id}",
    response_model=AIReportResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Report not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get AI Report by Submission",
    description="Retrieve AI report data for a specific submission (presentation)"
)
async def get_ai_report_by_submission(
    submission_id: int,
    db: Optional[object] = None
):
    """
    Get AI report data by submission/presentation ID

    Args:
        submission_id: The submission/presentation ID

    Returns:
        AI report data including overall score, criterion scores, and report content
    """
    logger.info(f"Getting AI report for submission_id={submission_id}")

    # Get database service
    if db is None:
        db_service = get_database_service()
    else:
        db_service = db

    # Get AI report from database
    report = db_service.get_ai_report(submission_id)

    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"AI report not found for submission {submission_id}"
        )

    return report


@app.get(
    "/api/v1/reports/presentation/{presentation_id}",
    response_model=AIReportResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Report not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    summary="Get AI Report by Presentation",
    description="Retrieve AI report data for a specific presentation (alias for submission)"
)
async def get_ai_report_by_presentation(
    presentation_id: int,
    db: Optional[object] = None
):
    """
    Get AI report data by presentation ID

    Args:
        presentation_id: The presentation ID

    Returns:
        AI report data including overall score, criterion scores, and report content
    """
    logger.info(f"Getting AI report for presentation_id={presentation_id}")

    # Get database service
    if db is None:
        db_service = get_database_service()
    else:
        db_service = db

    # Get AI report from database
    report = db_service.get_ai_report(presentation_id)

    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"AI report not found for presentation {presentation_id}"
        )

    return report


# Run server if executed directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level=settings.LOG_LEVEL.lower()
    )
