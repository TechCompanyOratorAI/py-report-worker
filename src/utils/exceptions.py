"""
Custom exceptions for py-report-worker
"""

class ReportWorkerError(Exception):
    """Base exception for report worker"""
    pass

class DatabaseError(ReportWorkerError):
    """Database operation error"""
    pass

class SQSError(ReportWorkerError):
    """SQS operation error"""
    pass

class WebhookError(ReportWorkerError):
    """Webhook operation error"""
    pass

class AnalysisError(ReportWorkerError):
    """Analysis processing error"""
    pass

class ConfigurationError(ReportWorkerError):
    """Configuration error"""
    pass
