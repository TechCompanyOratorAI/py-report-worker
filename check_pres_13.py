#!/usr/bin/env python
"""Check presentation 13 specifically"""

import sys
sys.path.insert(0, 'src')

from config.settings import settings
from services.database_service import DatabaseService

print("\n" + "="*80)
print("🔍 CHECKING PRESENTATION 13")
print("="*80 + "\n")

try:
    db = DatabaseService()
    
    print("Fetching Presentation ID 13...\n")
    pres_data = db.get_presentation_data(13)
    
    if pres_data:
        print("✅ PRESENTATION 13 FOUND!\n")
        print(f"Title: {pres_data.title}")
        print(f"Description: {pres_data.description}")
        print(f"Topic: {pres_data.topic_name}")
        print(f"Topic Description: {pres_data.topic_description}\n")
        
        print(f"📊 Data Summary:")
        print(f"   - Transcript Segments: {len(pres_data.transcript_segments)}")
        print(f"   - Slides: {len(pres_data.slides)}\n")
        
        if pres_data.transcript_segments:
            print(f"📝 Sample Segment (first):")
            seg = pres_data.transcript_segments[0]
            print(f"   ID: {seg.get('segmentId')}")
            print(f"   Text: {seg.get('segmentText', '')[:100]}...")
            print(f"   Start: {seg.get('startTimestamp')}s")
            print(f"   End: {seg.get('endTimestamp')}s\n")
        
        if pres_data.slides:
            print(f"🎨 Sample Slide (first):")
            slide = pres_data.slides[0]
            print(f"   Number: {slide.get('slideNumber')}")
            print(f"   Text: {slide.get('extractedText', '')[:100]}...\n")
        
        print("="*80)
        print("✅ DATA LOOKS GOOD - Worker should process it!")
        print("="*80)
        
    else:
        print("❌ PRESENTATION 13 NOT FOUND\n")
        print("Possible issues:")
        print("   1. ID doesn't exist")
        print("   2. Missing transcripts")
        print("   3. Missing slides")
        print("   4. No topic assigned\n")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
