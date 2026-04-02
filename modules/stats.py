import sqlite3
from config import DB_PATH


def get_overall_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
            SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN outcome = 'incorrect' THEN 1 ELSE 0 END) as incorrect,
            MAX(score) as best_score,
            AVG(score) as avg_score
        FROM signals
    ''')
    row = c.fetchone()

    c.execute('''
        SELECT COUNT(*) FROM signals
        WHERE sent_at >= datetime('now', '-24 hours')
    ''')
    today = c.fetchone()[0]

    conn.close()
    return {
        "total": row[0] or 0,
        "resolved": row[1] or 0,
        "correct": row[2] or 0,
        "incorrect": row[3] or 0,
        "best_score": row[4] or 0,
        "avg_score": round(row[5] or 0, 1),
        "today": today
    }


def get_category_accuracy() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT 
            category,
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) as correct
        FROM signals
        WHERE resolved = 1
        GROUP BY category
        ORDER BY total DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return [
        {
            "category": r[0] or "unknown",
            "total": r[1],
            "correct": r[2],
            "accuracy": round(r[2] / max(r[1], 1) * 100, 1)
        }
        for r in rows
    ]


def get_last_signals(limit=10) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT question, score, edge_pct, edge_direction, outcome, sent_at, category
        FROM signals
        ORDER BY sent_at DESC
        LIMIT ?
    ''', (limit,))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "question": r[0],
            "score": r[1],
            "edge_pct": r[2],
            "direction": r[3],
            "outcome": r[4],
            "sent_at": r[5],
            "category": r[6]
        }
        for r in rows
    ]
