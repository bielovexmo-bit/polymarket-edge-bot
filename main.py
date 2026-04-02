import time
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from collections import defaultdict

from config import *
from modules.db import (init_db, save_signal, save_volume,
                         get_avg_volume_7d, get_pending_signals, resolve_signal)
from modules.polymarket import get_all_active_markets, get_market_orderbook, classify_market
from modules.news import fetch_recent_news_rss, match_news_to_market, fetch_newsapi
from modules.wallet_tracker import WalletTracker
from modules.analyzer import get_ai_probability
from modules.scorer import score_opportunity
from modules.telegram_bot import send_signal, send_daily_summary, start_command_bot, send_resolution_notification
from modules.multi_outcome import (is_multi_outcome, parse_multi_outcome,
                                    get_multi_ai_analysis, score_multi_outcome,
                                    format_multi_signal)
from modules.tuner import run_tuner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
log = logging.getLogger(__name__)


# ─── Cross-market корреляции ──────────────────────────────────────────────────

CORRELATIONS = {
    "bitcoin":  ["microstrategy", "coinbase", "crypto etf", "btc"],
    "trump":    ["crypto bill", "sec chair", "defi", "executive order"],
    "fed":      ["bitcoin ath", "gold", "nasdaq", "rate cut"],
    "election": ["president", "senate", "congress", "poll"],
}

def find_correlated_signal(market_question: str, resolved_signals: list[str]) -> bool:
    q = market_question.lower()
    for resolved in resolved_signals:
        for category, keywords in CORRELATIONS.items():
            if category in resolved.lower():
                if any(kw in q for kw in keywords):
                    return True
    return False


# ─── Резолюции ────────────────────────────────────────────────────────────────

def _check_resolutions():
    """Проверяем не закрылись ли рынки по которым были сигналы"""
    pending = get_pending_signals()
    if not pending:
        return

    for signal_id, market_id, edge_direction, ai_prob, category in pending:
        try:
            r = requests.get(
                f"https://gamma-api.polymarket.com/markets/{market_id}",
                timeout=8
            )
            data = r.json()
            prices = data.get("outcomePrices", [])
            if not prices:
                continue

            yes_price = float(prices[0])

            if yes_price >= 0.97:
                resolved_price = 1.0
            elif yes_price <= 0.03:
                resolved_price = 0.0
            else:
                continue  # ещё не закрыт

            correct = (
                (edge_direction == "YES" and resolved_price == 1.0) or
                (edge_direction == "NO"  and resolved_price == 0.0)
            )
            outcome = "correct" if correct else "incorrect"
            resolve_signal(signal_id, outcome)

            # Тянем данные сигнала для уведомления
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                'SELECT question, edge_direction, edge_pct, score FROM signals WHERE id = ?',
                (signal_id,)
            )
            row = cur.fetchone()
            conn.close()

            if row:
                send_resolution_notification(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    question=row[0],
                    direction=row[1],
                    edge_pct=row[2],
                    outcome=outcome,
                    score=row[3]
                )

            log.info(f"✅ Резолюция [{signal_id}]: {'ВЕРНО' if correct else 'НЕВЕРНО'} ({edge_direction})")

        except Exception as e:
            log.debug(f"Резолюция {market_id}: {e}")


# ─── Основной цикл ────────────────────────────────────────────────────────────

def main():
    log.info("🚀 Polymarket Edge Bot v3 стартует...")

    # Инициализация БД
    init_db()

    # Запуск Telegram command-бота в фоне (/stats /accuracy /history)
    start_command_bot(TELEGRAM_BOT_TOKEN)

    # Загружаем умные кошельки
    tracker = WalletTracker(polygonscan_key=POLYGONSCAN_API_KEY)
    tracker.load_top_traders(min_profit=MIN_TRADER_PROFIT, limit=TOP_TRADERS_LIMIT)

    signal_cooldown: dict = {}
    resolved_signals: list[str] = []

    daily_stats = defaultdict(int)
    last_summary = datetime.utcnow()
    last_wallet_refresh = datetime.utcnow()
    last_tuner_run = datetime.utcnow()
    cycle = 0

    while True:
        try:
            cycle += 1
            log.info(f"─── Цикл #{cycle} ───")

            # Проверяем резолюции сигналов
            _check_resolutions()

            # Обновляем топ-кошельки раз в 6 часов
            if (datetime.utcnow() - last_wallet_refresh).seconds > 21600:
                tracker.load_top_traders(min_profit=MIN_TRADER_PROFIT)
                last_wallet_refresh = datetime.utcnow()

            # Запускаем tuner раз в сутки
            if (datetime.utcnow() - last_tuner_run).seconds > 86400:
                log.info("🧠 Запуск tuner...")
                run_tuner()
                last_tuner_run = datetime.utcnow()

            # 1. Тянем все активные рынки
            all_markets = get_all_active_markets(limit=200)
            daily_stats["scanned"] += len(all_markets)

            # 2. Фильтруем
            candidates = [m for m in all_markets if
                m["volume_24h"] >= MIN_VOLUME and
                m["days_to_close"] >= MIN_DAYS_TO_CLOSE and
                m["yes_price"] not in (0.0, 1.0)]

            log.info(f"Рынков: {len(all_markets)} | Кандидатов: {len(candidates)}")

            # Забытые рынки — приоритет
            neglected = [m for m in candidates if m["volume_24h"] <= MAX_VOLUME_NEGLECTED]
            popular   = [m for m in candidates if m["volume_24h"] >  MAX_VOLUME_NEGLECTED]
            ordered   = neglected + popular

            # 3. Свежие новости один раз на весь цикл
            fresh_news = fetch_recent_news_rss(max_age_hours=6)
            log.info(f"Свежих новостей: {len(fresh_news)}")

            # 4. Основной цикл по рынкам
            for market in ordered:
                mid = market["id"]

                # Cooldown
                last_signal = signal_cooldown.get(mid)
                if last_signal and (datetime.utcnow() - last_signal).seconds < SIGNAL_COOLDOWN_HOURS * 3600:
                    continue

                # Сохраняем volume для истории (avg_7d)
                save_volume(mid, market["volume_24h"])

                # Матчим новости
                news_headlines, news_age = match_news_to_market(market["question"], fresh_news)
                if len(news_headlines) < 3 and NEWS_API_KEY:
                    extra = fetch_newsapi(market["question"], NEWS_API_KEY)
                    news_headlines = (news_headlines + extra)[:8]

                # Классификация
                category = classify_market(market)
                market["category"] = category

                # ── MULTI-OUTCOME ветка ───────────────────────────────────────
                if is_multi_outcome(market):
                    outcomes_market = parse_multi_outcome(market)
                    multi_analysis = get_multi_ai_analysis(
                        question=market["question"],
                        description=market["description"],
                        outcomes=outcomes_market,
                        news_headlines=news_headlines
                    )
                    if not multi_analysis:
                        time.sleep(1)
                        continue

                    scored_outcomes, best_score = score_multi_outcome(
                        outcomes_market=outcomes_market,
                        outcomes_ai=multi_analysis.get("outcomes", []),
                        volume_24h=market["volume_24h"],
                        news_age_hours=news_age,
                        confidence=multi_analysis.get("confidence", "medium"),
                        days_to_close=market["days_to_close"]
                    )

                    log.info(f"  [MULTI/{best_score:3d}] {market['question'][:55]}")

                    if best_score >= MIN_SCORE:
                        text = format_multi_signal(market, scored_outcomes, multi_analysis, best_score)
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                            json={
                                "chat_id": TELEGRAM_CHAT_ID,
                                "text": text,
                                "parse_mode": "HTML",
                                "disable_web_page_preview": True
                            },
                            timeout=10
                        )

                        best_outcome = max(scored_outcomes, key=lambda x: abs(x["edge"]))
                        fake_breakdown = {
                            "edge_pct": best_outcome["edge"],
                            "edge_direction": best_outcome["name"],
                            "total": best_score
                        }
                        save_signal(
                            market, best_score, fake_breakdown,
                            best_outcome["ai_prob"],
                            multi_analysis.get("confidence", "medium"),
                            market_type="multi"
                        )

                        signal_cooldown[mid] = datetime.utcnow()
                        resolved_signals.append(market["question"])
                        if len(resolved_signals) > 50:
                            resolved_signals.pop(0)
                        daily_stats["signals"] += 1
                        daily_stats["best_score"] = max(daily_stats["best_score"], best_score)

                    time.sleep(1.5)
                    continue  # пропускаем binary ветку

                # ── BINARY ветка ──────────────────────────────────────────────
                analysis = get_ai_probability(
                    question=market["question"],
                    description=market["description"],
                    news_headlines=news_headlines,
                    market_prob=market["yes_price"],
                    category=category
                )
                if not analysis:
                    time.sleep(1)
                    continue

                ai_prob = analysis["probability"]

                smart_money = tracker.analyze_smart_money_for_market(mid, market["yes_price"])
                orderbook   = get_market_orderbook(mid)
                correlated  = find_correlated_signal(market["question"], resolved_signals)

                # Реальный avg_volume_7d из БД
                volume_avg_7d = get_avg_volume_7d(mid) or market["volume_24h"] * 0.7

                score, breakdown = score_opportunity(
                    ai_prob=ai_prob,
                    market_prob=market["yes_price"],
                    volume_24h=market["volume_24h"],
                    volume_avg_7d=volume_avg_7d,
                    news_age_hours=news_age,
                    confidence=analysis["confidence"],
                    smart_money=smart_money,
                    orderbook=orderbook,
                    days_to_close=market["days_to_close"],
                    correlated_signal=correlated
                )

                log.info(f"  [{score:3d}] {market['question'][:55]}")

                if score >= MIN_SCORE:
                    send_signal(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        market, analysis, smart_money, score, breakdown
                    )
                    save_signal(
                        market, score, breakdown,
                        ai_prob, analysis["confidence"],
                        market_type="binary"
                    )
                    signal_cooldown[mid] = datetime.utcnow()
                    resolved_signals.append(market["question"])
                    if len(resolved_signals) > 50:
                        resolved_signals.pop(0)
                    daily_stats["signals"] += 1
                    daily_stats["best_score"] = max(daily_stats["best_score"], score)

                time.sleep(1.5)

            # Дневной отчёт в 09:00 UTC
            if (datetime.utcnow() - last_summary).seconds > 86400:
                daily_stats["smart_wallets"] = len(tracker.smart_wallets)
                send_daily_summary(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, dict(daily_stats))
                daily_stats.clear()
                last_summary = datetime.utcnow()

            log.info(f"Цикл завершён. Следующий скан через {SCAN_INTERVAL}с...")
            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            log.info("Бот остановлен.")
            break
        except Exception as e:
            log.error(f"Ошибка главного цикла: {e}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
