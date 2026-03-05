#!/usr/bin/env python
"""Check processing progress from database"""
import sys
sys.path.insert(0, 'src')

from config.settings import settings
from services.database_service import DatabaseService
from services.sqs_service import SQSService
import json

print("\n" + "="*80)
print("📊 PROCESSING STATUS REPORT")
print("="*80 + "\n")

try:
    # Check queue
    sqs = SQSService()
    r = sqs.client.get_queue_attributes(
        QueueUrl=sqs.queue_url,
        AttributeNames=['ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible']
    )
    waiting = int(r['Attributes']['ApproximateNumberOfMessages'])
    processing = int(r['Attributes']['ApproximateNumberOfMessagesNotVisible'])
    
    print("📋 QUEUE STATUS:")
    print(f"   Waiting to process: {waiting}")
    print(f"   Currently processing: {processing}")
    print()
    
    # Check database
    db = DatabaseService()
    
    # Check SegmentAnalyses
    print("💾 DATABASE ANALYSIS PROGRESS:")
    cursor = db.connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM SegmentAnalyses")
    result = cursor.fetchone()
    segment_count = result[0] if result else 0
    
    print(f"   SegmentAnalyses saved: {segment_count}")
    
    # Check AnalysisResults
    cursor.execute("SELECT * FROM AnalysisResults ORDER BY createdAt DESC LIMIT 1")
    result = cursor.fetchone()
    
    if result and len(result) >= 5:
        print(f"   Latest AnalysisResults:")
        print(f"      - ID: {result[0]}")
        print(f"      - Presentation: {result[1]}")
        print(f"      - Overall Score: {result[2]}")
        print(f"      - Created: {result[5] if len(result) > 5 else 'N/A'}")
    
    cursor.close()
    
    print("\n" + "="*80)
    
    if waiting == 0 and processing == 0 and segment_count > 0:
        print("✅ PROCESSING COMPLETED!")
        print(f"   Total segments analyzed: {segment_count}")
    elif processing > 0:
        print(f"⏳ STILL PROCESSING {segment_count} segments analyzed so far...")
        print(f"   (Out of 223 total segments for presentation 13)")
    else:
        print("❓ UNKNOWN STATE")
    
    print("="*80 + "\n")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
