#!/usr/bin/env python
"""Simple one-shot progress check"""
import sys
sys.path.insert(0, 'src')

from config.settings import settings
import mysql.connector

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
    
    # Get segment count
    cursor.execute("SELECT COUNT(*) FROM SegmentAnalyses")
    seg_count = cursor.fetchone()[0]
    
    # Get results  
    cursor.execute("SELECT COUNT(*) FROM AnalysisResults WHERE presentationId = 13")
    result_count = cursor.fetchone()[0]
    
    conn.close()
    
    total = 223
    pct = (seg_count / total) * 100 if total > 0 else 0
    
    print(f"\nProgress: {seg_count}/{total} segments ({pct:.1f}%)")
    
    if result_count > 0:
        print("✅ JOB COMPLETED!")
    else:
        print("⏳ Still processing...")
    
except Exception as e:
    print(f"Error: {e}")
