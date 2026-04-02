from modules.multi_outcome import (is_multi_outcome, parse_multi_outcome,
                                    get_multi_ai_analysis, score_multi_outcome,
                                    format_multi_signal)

# В цикле for market in ordered: — после classify_market():

if is_multi_outcome(market):
    # ── Multi-outcome ветка ──
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
        # Отправляем через существующий send_signal но с готовым текстом
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)

        # Сохраняем лучший исход в БД
        best_outcome = max(scored_outcomes, key=lambda x: abs(x["edge"]))
        fake_breakdown = {
            "edge_pct": best_outcome["edge"],
            "edge_direction": best_outcome["name"],
            "total": best_score
        }
        save_signal(market, best_score, fake_breakdown,
                    best_outcome["ai_prob"], multi_analysis.get("confidence", "medium"),
                    market_type="multi")

        signal_cooldown[mid] = datetime.utcnow()
        daily_stats["signals"] += 1
        daily_stats["best_score"] = max(daily_stats["best_score"], best_score)

    time.sleep(1.5)
    continue  # пропускаем обычную binary ветку

# ── Binary ветка (существующий код) ──
analysis = get_ai_probability(...)
