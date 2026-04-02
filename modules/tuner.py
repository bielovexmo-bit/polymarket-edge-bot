import sqlite3
import logging
from datetime import datetime
from config import DB_PATH

log = logging.getLogger(__name__)

def recalculate_bias(category: str, min_samples: int = 15) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT outcome FROM signals
        WHERE category = ? AND resolved = 1 AND outcome != 'unresolved'
        ORDER BY sent_at DESC LIMIT 100
    ''', (category,))
    rows = c.fetchall()
    conn.close()

    if len(rows) < min_samples:
        return None

    total = len(rows)
    correct = sum(1 for (o,) in rows if o == 'correct')
    accuracy = correct / total

    # Если точность < 40% — AI переоценивает, увеличиваем magnitude с direction против
    # Если точность > 65% — AI хорошо работает, bias можно снижать
    if accuracy < 0.40:
        magnitude = 0.05 + (0.40 - accuracy) * 0.3
        direction = -1
    elif accuracy > 0.65:
        magnitude = max(0.0, 0.07 - (accuracy - 0.65) * 0.2)
        direction = 1
    else:
        magnitude = 0.04
        direction = 1

    magnitude = round(min(magnitude, 0.12), 3)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO category_stats 
        (category, total_signals, correct_signals, accuracy, suggested_bias_magnitude, suggested_bias_direction, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(category) DO UPDATE SET
            total_signals = excluded.total_signals,
            correct_signals = excluded.correct_signals,
            accuracy = excluded.accuracy,
            suggested_bias_magnitude = excluded.suggested_bias_magnitude,
            suggested_bias_direction = excluded.suggested_bias_direction,
            updated_at = excluded.updated_at
    ''', (category, total, correct, accuracy, magnitude, direction, datetime.utcnow()))
    conn.commit()
    conn.close()

    log.info(f"📊 Bias пересчитан [{category}]: accuracy={accuracy:.1%} → magnitude={magnitude}, dir={direction}")
    return {"direction": direction, "magnitude": magnitude}

def get_dynamic_bias_corrections() -> dict:
    """Возвращает BIAS_CORRECTIONS из БД. Если данных мало — вернёт пустой dict."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT category, suggested_bias_direction, suggested_bias_magnitude FROM category_stats')
    rows = c.fetchall()
    conn.close()
    return {cat: {"direction": d, "magnitude": m} for cat, d, m in rows}

def run_tuner():
    """Запускать раз в сутки из main.py"""
    categories = ["crypto", "politics_usa", "regulation", "long_term_90d", "general"]
    for cat in categories:
        recalculate_bias(cat)
