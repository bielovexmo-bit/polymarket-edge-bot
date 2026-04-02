import time
import logging
import sqlite3
from datetime import datetime
from collections import defaultdict

import requests

from config import DB_PATH, OPENAI_API_KEY, NEWS_API_KEY
from modules.db import init_db, save_signal, resolve_signal
from modules.polymarket import classify_market
from modules.analyzer import get_ai_probability, BIAS_CORRECTIONS
from modules.scorer import score_opportunity
from modules.tuner import run_tuner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


# ─── 1. Тянем закрытые рынки ─────────────────────────────────────────────────

def fetch_closed_markets(limit=500) -> list[dict]:
    """Закрытые рынки с известным исходом"""
    url = f"{GAMMA_API}/markets"
    params = {
        "closed": "true",
        "limit": limit,
        "order": "volume",
        "ascending": "false"
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    markets = []
    for m in r.json():
        try:
            prices = m.get("outcomePrices", ["0.5", "0.5"])
            yes_price_final = float(prices[0]) if prices else 0.5

            # Нам нужны только чётко резолвнувшиеся
            if yes_price_final not in (0.0, 1.0) and yes_price_final > 0.03 and yes_price_final < 0.97:
                continue

            # Восстанавливаем примерную цену ДО закрытия из истории
            # Берём среднюю — если рынок закрылся на 1.0, до этого мог быть на 0.4-0.8
            # Используем поле "initialOdds" или строим моки
            initial_yes = float(m.get("initialOdds", [0.5])[0]) if m.get("initialOdds") else None
            if initial_yes is None:
                # Моделируем: если исход YES — берём цену как 0.5-0.75 (рынок не знал)
                initial_yes = 0.65 if yes_price_final == 1.0 else 0.35

            markets.append({
                "id": m["id"],
                "question": m.get("question", ""),
                "description": m.get("description", "")[:600],
                "yes_price": initial_yes,           # цена ДО резолюции (мок)
                "yes_price_final": yes_price_final,  # реальный исход
                "volume_24h": float(m.get("volume24hr") or 1000),
                "volume_total": float(m.get("volume") or 0),
                "unique_traders": int(m.get("uniqueTraders") or 0),
                "days_to_close": 5,  # мок — рынок был активен
                "category": m.get("category", "").lower(),
                "slug": m.get("slug", m["id"]),
                "url": f"https://polymarket.com/event/{m.get('slug', m['id'])}"
            })
        except Exception:
            continue

    log.info(f"Загружено закрытых рынков: {len(markets)}")
    return markets


# ─── 2. Прогоняем через scorer без smart money и orderbook ───────────────────

def run_backtest(markets: list[dict], min_score: int = 55) -> dict:
    """
    Прогоняем закрытые рынки через AI + scorer.
    Smart money и orderbook пропускаем — нет исторических данных.
    """
    stats = defaultdict(lambda: {"total": 0, "correct": 0, "signals": 0})
    results = []
    total = len(markets)

    for i, market in enumerate(markets):
        try:
            category = classify_market(market)
            market["category"] = category

            # AI анализ (реальный вызов GPT)
            analysis = get_ai_probability(
                question=market["question"],
                description=market["description"],
                news_headlines=[],  # нет исторических новостей
                market_prob=market["yes_price"],
                category=category
            )
            if not analysis:
                time.sleep(1)
                continue

            ai_prob = analysis["probability"]

            # Скоринг без smart money и orderbook
            score, breakdown = score_opportunity(
                ai_prob=ai_prob,
                market_prob=market["yes_price"],
                volume_24h=market["volume_24h"],
                volume_avg_7d=market["volume_24h"] * 0.7,
                news_age_hours=999,   # нет новостей
                confidence=analysis["confidence"],
                smart_money={"found": False},
                orderbook={"signal": "NEUTRAL", "hidden_wall": False},
                days_to_close=market["days_to_close"],
                correlated_signal=False
            )

            # Определяем верность сигнала
            edge_direction = breakdown["edge_direction"]
            yes_final = market["yes_price_final"]
            correct = (
                (edge_direction == "YES" and yes_final >= 0.97) or
                (edge_direction == "NO"  and yes_final <= 0.03)
            )
            outcome = "correct" if correct else "incorrect"

            # Сохраняем в БД как реальный сигнал
            signal_id = save_signal(market, score, breakdown, ai_prob, analysis["confidence"])
            resolve_signal(signal_id, outcome)

            # Статистика
            stats[category]["total"] += 1
            stats[category]["correct"] += int(correct)
            if score >= min_score:
                stats[category]["signals"] += 1
                results.append({
                    "question": market["question"][:60],
                    "score": score,
                    "edge": breakdown["edge_pct"],
                    "direction": edge_direction,
                    "outcome": outcome,
                    "category": category
                })

            if i % 20 == 0:
                log.info(f"Прогресс: {i}/{total}")

            time.sleep(1.2)  # rate limit OpenAI

        except Exception as e:
            log.error(f"Ошибка рынка {market.get('id')}: {e}")
            continue

    return dict(stats), results


# ─── 3. Отчёт по бэктесту ────────────────────────────────────────────────────

def print_backtest_report(stats: dict, results: list):
    print("\n" + "="*60)
    print("📊 BACKTEST REPORT")
    print("="*60)

    total_all = sum(v["total"] for v in stats.values())
    correct_all = sum(v["correct"] for v in stats.values())
    signals_all = sum(v["signals"] for v in stats.values())

    print(f"\nВсего рынков обработано: {total_all}")
    print(f"Сигналов (score >= 55):  {signals_all}")
    print(f"Общая точность AI:       {correct_all/max(total_all,1)*100:.1f}%")

    print("\n── Точность по категориям ──")
    for cat, s in sorted(stats.items(), key=lambda x: -x[1]["total"]):
        acc = s["correct"] / max(s["total"], 1) * 100
        print(f"  {cat:<20} {acc:5.1f}%  ({s['correct']}/{s['total']}) | сигналов: {s['signals']}")

    print("\n── Топ-10 сигналов бэктеста ──")
    top = sorted(results, key=lambda x: -x["score"])[:10]
    for r in top:
        icon = "✅" if r["outcome"] == "correct" else "❌"
        print(f"  {icon} [{r['score']:3d}] {r['direction']} {r['edge']:+.1f}% | {r['question']}")

    print("="*60)


# ─── 4. Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("🔬 Запуск бэктеста...")
    init_db()

    markets = fetch_closed_markets(limit=300)
    if not markets:
        log.error("Нет данных для бэктеста")
        exit(1)

    stats, results = run_backtest(markets, min_score=55)
    print_backtest_report(stats, results)

    log.info("🧠 Запускаем tuner на данных бэктеста...")
    run_tuner()
    log.info("✅ Tuner завершён — BIAS_CORRECTIONS откалиброваны")
