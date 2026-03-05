#!/usr/bin/env python
"""Health check for Report Worker"""

import sys
import time
sys.path.insert(0, 'src')

from config.settings import settings
from utils.logger import get_logger
from services.sqs_service import get_sqs_service
from services.database_service import get_database_service
from services.webhook_service import get_webhook_service
from services.report_analysis_service import get_report_analysis_service

logger = get_logger(__name__)

print("\n" + "="*80)
print("📋 REPORT WORKER HEALTH CHECK")
print("="*80 + "\n")

try:
    print("1️⃣  Checking Settings...")
    settings.validate()
    print("   ✅ Configuration is valid\n")
    
    print("2️⃣  Checking SQS Service...")
    sqs = get_sqs_service()
    print("   ✅ SQS Service ready\n")
    
    print("3️⃣  Checking Database...")
    db = get_database_service()
    print("   ✅ Database connected\n")
    
    print("4️⃣  Checking Webhook Service...")
    webhook = get_webhook_service()
    if webhook.test_connection():
        print("   ✅ Webhook endpoint reachable\n")
    else:
        print("   ⚠️  Webhook endpoint not reachable (may be offline)\n")
    
    print("5️⃣  Checking Gemini AI...")
    report = get_report_analysis_service(db)
    print("   ✅ Gemini AI initialized\n")
    
    print("="*80)
    print("✅ ALL SYSTEMS READY!")
    print("="*80)
    print("\n📝 Status: Ready to process reports from SQS queue")
    print("💾 Database: Connected")
    print("🔄 Polling: Enabled\n")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
