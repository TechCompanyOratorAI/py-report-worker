#!/usr/bin/env python
"""Simple progress indicator"""
import sys
import time
import threading
sys.path.insert(0, 'src')

from config.settings import settings
from services.sqs_service import SQSService

def monitor():
    """Monitor and display progress"""
    sqs = SQSService()
    start = time.time()
    last_status = None
    
    while True:
        try:
            r = sqs.client.get_queue_attributes(
                QueueUrl=sqs.queue_url,
                AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
            )
            waiting = int(r['Attributes']['ApproximateNumberOfMessages'])
            processing = int(r['Attributes']['ApproximateNumberOfMessagesNotVisible'])
            
            status = f"[{time.time()-start:.0f}s] Waiting: {waiting} | Processing: {processing}"
            
            if status != last_status or processing == 0:
                print(status)
                last_status = status
            
            if waiting == 0 and processing == 0:
                print("\n✅ All done! Queue is empty.")
                break
                
            time.sleep(2)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    monitor()
