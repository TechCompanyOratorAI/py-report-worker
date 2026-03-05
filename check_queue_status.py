#!/usr/bin/env python
"""Check SQS queue status"""

import sys
sys.path.insert(0, 'src')

from config.settings import settings
from services.sqs_service import SQSService

print("\n" + "="*80)
print("📋 CHECKING SQS QUEUE STATUS")
print("="*80 + "\n")

try:
    sqs = SQSService()
    response = sqs.client.get_queue_attributes(
        QueueUrl=sqs.queue_url,
        AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
    )
    
    attributes = response.get('Attributes', {})
    messages_visible = int(attributes.get('ApproximateNumberOfMessages', 0))
    messages_processing = int(attributes.get('ApproximateNumberOfMessagesNotVisible', 0))
    
    print(f"Queue URL: {sqs.queue_url}\n")
    print(f"📊 Queue Status:")
    print(f"   - Messages waiting: {messages_visible}")
    print(f"   - Messages being processed: {messages_processing}")
    print(f"   - Total: {messages_visible + messages_processing}\n")
    
    if messages_visible > 0:
        print(f"⏳ Messages in queue. Worker should pick them up within 20 seconds.\n")
    elif messages_processing > 0:
        print(f"🔄 Messages are being processed by worker!\n")
    else:
        print(f"✅ Queue is empty - all messages have been processed.\n")
    
    print("="*80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
