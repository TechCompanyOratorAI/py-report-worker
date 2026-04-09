"""
Check SpeechQualityAnalyses data for a presentation
"""
import sys
sys.path.insert(0, '.')

from src.services.database_service import DatabaseService
from src.config.settings import settings

def check_speech_quality(presentation_id: int):
    db = DatabaseService()
    
    # Check SpeechQualityAnalyses
    print(f"\n=== SpeechQualityAnalyses for presentation {presentation_id} ===")
    result = db.get_speech_quality_analysis(presentation_id)
    if result:
        print(f"Found record:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    else:
        print("No SpeechQualityAnalyses record found!")
    
    # Check if there are any records at all
    print(f"\n=== All SpeechQualityAnalyses (last 5) ===")
    db._ensure_connection()
    cursor = db.connection.cursor(dictionary=True)
    cursor.execute("""
        SELECT presentationId, fluencyScore, clarityScore, confidenceScore, 
               overallScore, totalHesitationCount, speakingRate
        FROM SpeechQualityAnalyses 
        ORDER BY createdAt DESC 
        LIMIT 5
    """)
    rows = cursor.fetchall()
    cursor.close()
    
    if rows:
        for row in rows:
            print(f"  Presentation {row['presentationId']}: fluency={row['fluencyScore']}, "
                  f"clarity={row['clarityScore']}, overall={row['overallScore']}, "
                  f"hesitations={row['totalHesitationCount']}, speakingRate={row['speakingRate']}")
    else:
        print("  No records in SpeechQualityAnalyses table!")
    
    db.close()

if __name__ == "__main__":
    # Default presentation_id, can change
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 34
    check_speech_quality(pid)
