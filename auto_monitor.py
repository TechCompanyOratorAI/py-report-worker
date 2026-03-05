#!/usr/bin/env python
"""Auto-monitor processing and notify when done"""
import sys
import time
sys.path.insert(0, 'src')

from config.settings import settings
import mysql.connector

def check_status():
    try:
        conn = mysql.connector.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            ssl_disabled=not settings.DB_SSL
        )
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM SegmentAnalyses")
        segment_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT * FROM AnalysisResults ORDER BY createdAt DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        return segment_count, result
    except Exception as e:
        return 0, None

print("\n" + "="*70)
print("AUTO MONITOR - Processing Status Updates")
print("="*70 + "\n")

start = time.time()
last_count = 0
checking = True
total_segments = 223

while checking:
    try:
        segment_count, result = check_status()
        progress = (segment_count / total_segments) * 100
        elapsed = int(time.time() - start)
        
        if segment_count > last_count:
            eta = int((total_segments - segment_count) * 2) if segment_count > 0 else 0
            print(f"[{elapsed:3d}s] {segment_count:3d}/{total_segments} segments | {progress:5.1f}% | ETA: {eta//60}m {eta%60}s")
            last_count = segment_count
        
        if result:  # If AnalysisResults exists (any result means processing completed)
            print("\n" + "="*70)
            print("✅ PROCESSING COMPLETED!")
            print("="*70)
            print(f"Total time: {elapsed} seconds ({elapsed//60}m {elapsed%60}s)")
            print(f"Segments processed: {segment_count}")
            score = result[2] if result[2] is not None else 0
            print(f"Overall Score: {score:.3f}")
            print(f"Completed at: {result[5] if len(result) > 5 else 'N/A'}")
            print("="*70 + "\n")
            checking = False
        elif elapsed > 900:  # 15 minutes max
            print(f"\n⚠️  Timeout - 15 minutes elapsed")
            print(f"Segments processed: {segment_count}")
            checking = False
        
        if checking:
            time.sleep(3)  # Check every 3 seconds
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
        checking = False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        time.sleep(5)

print("\n✅ Monitor finished.\n")
