import sqlite3
import logging
from datetime import datetime
from config import DB_PATH

log = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            question TEXT,
            category TEXT,
            yes_price_at_signal REAL,
            ai_probability REAL,
            edge_pct REAL,
            edge_direction TEXT,
            score INTEGER,
            confidence TEXT,
            volume_24h REAL,
            days_to_close INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved INTEGER DEFAULT 0,
            outcome TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS volume_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            volume_24h REAL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS category_stats (
            category TEXT PRIMARY KEY,
            total_signals INTEGER DEFAULT 0,
            correct_signals INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0.0,
            suggested_bias_magnitude REAL DEFAULT 0.0,
            suggested_bias_direction INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    log.info("✅ DB инициализирована")

def save_signal(market: dict, score: int, breakdown: dict, ai_prob: float, confidence: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO signals 
        (market_id, question, category, yes_price_at_signal, ai_probability,
         edge_pct, edge_direction, score, confidence, volume_24h, days_to_close)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        market["id"], market["question"], market.get("category"),
        market["yes_price"], ai_prob,
        breakdown["edge_pct"], breakdown["edge_direction"],
        score, confidence, market["volume_24h"], market["days_to_close"]
    ))
    signal_id = c.lastrowid
    conn.commit()
    conn.close()
    return signal_id

def save_volume(market_id: str, volume_24h: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO volume_history (market_id, volume_24h) VALUES (?, ?)',
              (market_id, volume_24h))
    conn.commit()
    conn.close()

def get_avg_volume_7d(market_id: str) -> float:
    """Реальный avg_volume_7d из истории вместо * 0.7"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT AVG(volume_24h) FROM volume_history
        WHERE market_id = ?
        AND recorded_at >= datetime('now', '-7 days')
    ''', (market_id,))
    result = c.fetchone()[0]
    conn.close()
    return result or 0.0

def get_pending_signals():
    """Сигналы без результата по рынкам которые могли уже резолвнуться"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT id, market_id, edge_direction, ai_probability, category
        FROM signals
        WHERE resolved = 0
        AND sent_at < datetime('now', '-1 hours')
    ''')
    rows = c.fetchall()
    conn.close()
    return rows

def resolve_signal(signal_id: int, outcome: str):
    """outcome: 'correct', 'incorrect', 'unresolved'"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE signals SET resolved = 1, outcome = ? WHERE id = ?
    ''', (outcome, signal_id))
    conn.commit()
    conn.close()
