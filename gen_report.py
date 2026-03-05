#!/usr/bin/env python
"""Generate HTML report of analysis results"""
import sys
sys.path.insert(0, 'src')

from config.settings import settings
import mysql.connector
import json

html_content = """
<html>
<head>
<meta charset="UTF-8">
<style>
body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
.container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
h1, h2 { color: #333; border-bottom: 2px solid #0066cc; padding-bottom: 10px; }
.result-card { background: #f9f9f9; border-left: 4px solid #0066cc; padding: 15px; margin: 10px 0; }
.score { font-size: 24px; font-weight: bold; color: #0066cc; }
table { width: 100%; border-collapse: collapse; margin: 20px 0; }
th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
th { background: #0066cc; color: white; }
tr:hover { background: #f5f5f5; }
.status-ok { color: #28a745; }
.status-pending { color: #ff9800; }
</style>
</head>
<body>
<div class="container">
<h1>📊 Presentation Analysis Results</h1>
"""

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
    
    # Get completed analyses
    cursor.execute("""
        SELECT 
            ar.resultId,
            ar.presentationId,
            p.title,
            ar.overallScore,
            ar.analyzedAt
        FROM AnalysisResults ar
        LEFT JOIN Presentations p ON ar.presentationId = p.presentationId
        ORDER BY ar.analyzedAt DESC
    """)
    
    results = cursor.fetchall()
    html_content += f"<h2>✅ Completed Analyses ({len(results)})</h2>\n"
    
    if results:
        for row in results:
            result_id, pres_id, title, overall, analyzed_at = row
            html_content += f"""
<div class="result-card">
  <p><strong>Result ID:</strong> {result_id} | <strong>Presentation:</strong> {pres_id} - {title or 'N/A'}</p>
  <p><strong>Overall Score:</strong> <span class="score">{overall if overall else 'N/A'}</span></p>
  <p><small>Created: {analyzed_at}</small></p>
</div>
"""
    
    # Segments summary
    cursor.execute("SELECT COUNT(*) FROM SegmentAnalyses")
    total_segments = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT presentationId, COUNT(*) as cnt, AVG(relevanceScore), AVG(semanticScore), AVG(alignmentScore)
        FROM SegmentAnalyses
        GROUP BY presentationId
        ORDER BY presentationId DESC
    """)
    
    seg_results = cursor.fetchall()
    html_content += f"""
<h2>📈 Segment Analysis Summary ({total_segments} total segments)</h2>
<table>
    <tr>
        <th>Presentation</th>
        <th>Segments</th>
        <th>Avg Relevance</th>
        <th>Avg Semantic</th>
        <th>Avg Alignment</th>
    </tr>
"""
    
    for pres_id, count, rel, sem, align in seg_results:
        html_content += f"""
    <tr>
        <td>{pres_id}</td>
        <td>{count}</td>
        <td>{f'{rel:.3f}' if rel else 'N/A'}</td>
        <td>{f'{sem:.3f}' if sem else 'N/A'}</td>
        <td>{f'{align:.3f}' if align else 'N/A'}</td>
    </tr>
"""
    
    html_content += """
</table>
"""
    
    conn.close()
    
except Exception as e:
    html_content += f"<h2>❌ Error: {e}</h2>\n"
    import traceback
    html_content += f"<pre>{traceback.format_exc()}</pre>\n"

html_content += """
</div>
</body>
</html>
"""

with open('analysis_report.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("✅ Report generated: analysis_report.html")
