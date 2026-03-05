#!/usr/bin/env python
"""Check and seed sample presentation data for testing"""

import sys
sys.path.insert(0, 'src')

from config.settings import settings
from services.database_service import DatabaseService
from utils.logger import get_logger

logger = get_logger(__name__)

print("\n" + "="*80)
print("🔍 CHECKING DATABASE FOR PRESENTATIONS")
print("="*80 + "\n")

try:
    db = DatabaseService()
    
    # Get all presentations
    print("Checking presentations in database...\n")
    
    # Try to get presentation 1
    print("1️⃣  Checking Presentation ID 1...")
    pres_data = db.get_presentation_data(1)
    
    if pres_data:
        print(f"   ✅ Found!")
        print(f"      Title: {pres_data.title}")
        print(f"      Topic: {pres_data.topic_name}")
        print(f"      Segments: {len(pres_data.transcript_segments)}")
        print(f"      Slides: {len(pres_data.slides)}\n")
    else:
        print(f"   ❌ NOT FOUND\n")
        print("⚠️  Sample data needs to be created in database!\n")
        print("   To test the worker, you need:")
        print("   1. A Presentation record")
        print("   2. Associated TranscriptSegments")
        print("   3. Associated Slides")
        print("   4. A Topic linked to the presentation\n")
    
    # Check database connection
    print("2️⃣  Database connection...")
    print(f"   ✅ Connected to: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}\n")
    
    # Try to count presentations
    print("3️⃣  Counting total presentations...")
    try:
        cursor = db.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM Presentations")
        result = cursor.fetchone()
        count = result[0] if result else 0
        print(f"   Total presentations: {count}\n")
        cursor.close()
    except Exception as e:
        print(f"   Error querying presentations: {e}\n")
    
    print("="*80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
