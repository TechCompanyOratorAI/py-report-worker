#!/usr/bin/env python
"""Check what presentation is being analyzed and results"""
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
    print("📊 ANALYSIS RESULTS CHECK")
    print("="*80 + "\n")
    
    # Check AnalysisResults (overall scores)
    print("1️⃣  COMPLETED ANALYSIS RESULTS:")
    cursor.execute("""
        SELECT 
            ar.resultId,
            ar.presentationId,
            p.title,
            ar.contentRelevance,
            ar.semanticSimilarity,
            ar.slideAlignment,
            ar.overallScore,
            ar.createdAt
        FROM AnalysisResults ar
        LEFT JOIN Presentations p ON ar.presentationId = p.presentationId
        ORDER BY ar.createdAt DESC
        LIMIT 5
    """)
    
    results = cursor.fetchall()
    if results:
        for row in results:
            result_id, pres_id, title, relevance, semantic, alignment, overall, created = row
            print(f"\n   Result ID: {result_id}")
            print(f"   Presentation: {pres_id} - {title}")
            print(f"   Overall Score: {overall:.3f}")
            if relevance is not None:
                print(f"   - Content Relevance: {relevance:.3f}")
                print(f"   - Semantic Similarity: {semantic:.3f}")
                print(f"   - Slide Alignment: {alignment:.3f}")
            print(f"   Created: {created}")
    else:
        print("   ❌ No analysis results found")
    
    # Check SegmentAnalyses
    print("\n2️⃣  SEGMENT ANALYSES (Detail):")
    cursor.execute("""
        SELECT COUNT(*), AVG(relevanceScore), AVG(semanticScore), AVG(alignmentScore)
        FROM SegmentAnalyses
    """)
    
    seg_row = cursor.fetchone()
    if seg_row and seg_row[0] > 0:
        seg_count, avg_relevance, avg_semantic, avg_alignment = seg_row
        print(f"   Total segments analyzed: {seg_count}")
        print(f"   Avg Relevance Score: {avg_relevance:.3f}" if avg_relevance else "   No data")
        print(f"   Avg Semantic Score: {avg_semantic:.3f}" if avg_semantic else "   No data")
        print(f"   Avg Alignment Score: {avg_alignment:.3f}" if avg_alignment else "   No data")
    else:
        print("   ❌ No segment analyses found")
    
    # Check by presentation
    print("\n3️⃣  SEGMENT ANALYSIS BY PRESENTATION:")
    cursor.execute("""
        SELECT 
            sa.presentationId,
            COUNT(*) as segment_count,
            AVG(sa.relevanceScore) as avg_relevance,
            AVG(sa.semanticScore) as avg_semantic,
            AVG(sa.alignmentScore) as avg_alignment
        FROM SegmentAnalyses sa
        GROUP BY sa.presentationId
        ORDER BY sa.presentationId DESC
        LIMIT 5
    """)
    
    seg_results = cursor.fetchall()
    if seg_results:
        for pres_id, count, rel, sem, align in seg_results:
            print(f"\n   Presentation {pres_id}:")
            print(f"      Segments: {count}")
            if rel:
                print(f"      Avg Relevance: {rel:.3f}")
                print(f"      Avg Semantic: {sem:.3f}")
                print(f"      Avg Alignment: {align:.3f}")
    else:
        print("   ❌ No segment data")
    
    conn.close()
    
    print("\n" + "="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
