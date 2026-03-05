#!/usr/bin/env python
"""Check database schema"""
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
    
    print("\n" + "="*80)
    print("DATABASE SCHEMA CHECK")
    print("="*80 + "\n")
    
    # Check AnalysisResults columns
    print("📋 AnalysisResults table columns:")
    cursor.execute("DESCRIBE AnalysisResults")
    for row in cursor.fetchall():
        print(f"   {row[0]:30} {row[1]}")
    
    # Sample data
    print("\n📊 Sample AnalysisResults data:")
    cursor.execute("SELECT * FROM AnalysisResults LIMIT 1")
    result = cursor.fetchone()
    
    if result:
        print(f"   Row data: {result}")
        print(f"   Total columns: {len(result)}")
    
    # Check SegmentAnalyses schema
    print("\n📋 SegmentAnalyses table columns:")
    cursor.execute("DESCRIBE SegmentAnalyses")
    for row in cursor.fetchall():
        print(f"   {row[0]:30} {row[1]}")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
