#!/usr/bin/env python
"""Direct test of Gemini API call"""

import sys
import json
sys.path.insert(0, 'src')

from config.settings import settings
from utils.logger import get_logger
from services.database_service import DatabaseService
from services.report_analysis_service import ReportAnalysisService

logger = get_logger(__name__)

print("\n" + "="*80)
print("🧪 TESTING GEMINI API CALL")
print("="*80 + "\n")

try:
    # Initialize settings
    print("1️⃣  Validating configuration...")
    settings.validate()
    print("   ✅ Configuration valid\n")
    
    # Check API key
    print("2️⃣  Checking Gemini API Key...")
    if settings.GEMINI_API_KEY:
        api_key_preview = settings.GEMINI_API_KEY[:10] + "..." + settings.GEMINI_API_KEY[-10:]
        print(f"   ✅ API Key found: {api_key_preview}\n")
    else:
        print("   ❌ API Key not found!\n")
        sys.exit(1)
    
    # Initialize database service
    print("3️⃣  Initializing Database Service...")
    db = DatabaseService()
    print("   ✅ Database Service initialized\n")
    
    # Initialize analysis service
    print("4️⃣  Initializing Report Analysis Service...")
    report_service = ReportAnalysisService(db)
    print("   ✅ Report Analysis Service initialized\n")
    
    # Create test data
    print("5️⃣  Creating test data...")
    test_segment = {
        'segmentId': 1,
        'segmentText': 'Today we will discuss machine learning and deep neural networks which are essential technologies. Machine learning is a subset of artificial intelligence.',
        'startTimestamp': 0.0,
        'endTimestamp': 5.0,
        'slideId': 1
    }
    
    topic_keywords = ['machine learning', 'deep learning', 'neural networks', 'artificial intelligence', 'technology']
    slide_contents = {
        1: 'Introduction to Machine Learning - What is ML? How does it work? Applications of ML in industry'
    }
    slides = [{'slideNumber': 1, 'extractedText': 'Introduction to Machine Learning'}]
    
    print("   ✅ Test data created\n")
    
    # Test Gemini API call
    print("6️⃣  Calling Gemini API to analyze segment...")
    print("   Sending prompt to Gemini...\n")
    
    result = report_service._analyze_segment(
        segment=test_segment,
        topic_keywords=topic_keywords,
        slide_contents=slide_contents,
        slides=slides,
        total_duration=300.0,
        total_segments=10
    )
    
    print("   ✅ Gemini API Response Received!\n")
    
    # Display results
    print("="*80)
    print("📊 ANALYSIS RESULT:")
    print("="*80)
    print(f"Segment ID: {result.segment_id}")
    print(f"Relevance Score: {result.relevance_score:.3f}")
    print(f"Semantic Score: {result.semantic_score:.3f}")
    print(f"Alignment Score: {result.alignment_score:.3f}")
    print(f"Best Matching Slide: {result.best_matching_slide}")
    print(f"Expected Slide: {result.expected_slide_number}")
    print(f"Timing Deviation: {result.timing_deviation}")
    print(f"Issues: {result.issues}")
    print(f"Suggestions: {result.suggestions}")
    print(f"Keywords Found: {result.topic_keywords_found}")
    print("="*80)
    
    print("\n✅ SUCCESS! Gemini API call completed successfully!")
    print("\n💡 This means:")
    print("   - Gemini API key is valid")
    print("   - Network connection to Google is working")
    print("   - Gemini model is responsive")
    print("   - JSON parsing is working")
    print("\n🚀 The worker can now analyze presentation segments!\n")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
