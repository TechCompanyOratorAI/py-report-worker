#!/usr/bin/env python
"""Direct database query for progress"""
import sys
import time
sys.path.insert(0, 'src')

from config.settings import settings
import mysql.connector

start_time = time.time()

try:
    # Connect directly
    conn = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        ssl_disabled=not settings.DB_SSL
    )
    
    cursor = conn.cursor()
    
    # Check segments
    cursor.execute("SELECT COUNT(*) FROM SegmentAnalyses")
    segment_count = cursor.fetchone()[0]
    
    # Check if job completed
    cursor.execute("SELECT * FROM AnalysisResults ORDER BY createdAt DESC LIMIT 1")
    result = cursor.fetchone()
    
    conn.close()
    
    elapsed = time.time() - start_time
    
    print("\n" + "="*70)
    print("PROGRESS CHECK")
    print("="*70)
    print(f"Segments analyzed: {segment_count}/223")
    print(f"Progress: {(segment_count/223)*100:.1f}%")
    
    if result:
        print(f"✅ Job COMPLETED!")
        print(f"   Overall Score: {result[2]:.3f}")
        print(f"   Finished at: {result[5]}")
    else:
        if segment_count > 0:
            eta_seconds = (223 - segment_count) * (elapsed / segment_count)
            print(f"⏳ Still processing...")
            print(f"   Est. time remaining: {eta_seconds:.0f} seconds (~{eta_seconds/60:.1f} minutes)")
        else:
            print(f"⏳ Just started or still initializing...")
    
    print("="*70 + "\n")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
