#!/usr/bin/env python
"""Monitor SQS queue continuously"""

import sys
import time
sys.path.insert(0, 'src')

from config.settings import settings
from services.sqs_service import SQSService

print("\n" + "="*80)
print("QUEUE MONITOR - Real-time Queue Status")
print("="*80 + "\n")

try:
    sqs = SQSService()
    iteration = 0
    
    while True:
        iteration += 1
        
        # Get queue attributes
        response = sqs.client.get_queue_attributes(
            QueueUrl=sqs.queue_url,
            AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
        )
        
        attributes = response.get('Attributes', {})
        messages_visible = int(attributes.get('ApproximateNumberOfMessages', 0))
        messages_processing = int(attributes.get('ApproximateNumberOfMessagesNotVisible', 0))
        
        print(f"[Iteration {iteration}] Waiting: {messages_visible} | Processing: {messages_processing} | Time: {time.strftime('%H:%M:%S')}")
        
        if messages_visible == 0 and messages_processing == 0:
            print("\n✅ Queue is empty - All messages processed!")
            break
        
        time.sleep(5)  # Check every 5 seconds
    
except KeyboardInterrupt:
    print("\n\nMonitoring stopped by user")
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
