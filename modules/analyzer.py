import logging
import json
from openai import OpenAI
from config import OPENAI_API_KEY

log = logging.getLogger(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)


# ─── Детект multi-outcome рынка ───────────────────────────────────────────────

def is_multi_outcome(market: dict) -> bool:
    prices = market.get("outcomePrices", [])
    outcomes = market.get("outcomes", [])
    return len(prices) >= 3 and len(outcomes) >= 3


def parse_multi_outcome(market: dict) -> list[dict]:
    """Парсим все исходы с их текущими ценами"""
    prices = market.get("outcomePrices", [])
    outcomes = market.get("outcomes", [])
    result = []
    for i, (outcome, price) in enumerate(zip(outcomes, prices)):
        try:
            result.append({
                "index": i,
                "name": outcome,
                "market_prob": float(price)
            })
        except Exception:
            continue
    return result


# ─── AI анализ для multi-outcome ──────────────────────────────────────────────

MULTI_SYSTEM_PROMPT = """You are an expert prediction market analyst.
Evaluate the TRUE probability for each outcome in this multi-outcome market.

Respond ONLY in valid JSON:
{
  "outcomes": [
    {"name": "<outcome name>", "probability": <integer 0-100>},
    ...
  ],
  "confidence": <"low"|"medium"|"high">,
  "key_factor": "<single most important factor>",
  "reasoning": "<2-3 sentences max>"
}

Probabilities must sum to 100. Be calibrated."""


def get_multi_ai_analysis(question: str, description: str,
                           outcomes: list[dict], news_headlines: list[str]) -> dict | None:
    outcomes_text = "\n".join(
        f"• {o['name']}: market={o['market_prob']*100:.1f}%"
        for o in outcomes
    )
    news_text = "\n".join(f"• {h}" for h in news_headlines[:6]) or "No recent news."

    user_msg = f"""Market: {question}
Description: {description[:400]}

Current market prices:
{outcomes_text}

Recent news:
{news_text}

What are the TRUE probabilities for each outcome?"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": MULTI_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=400
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        log.error(f"Multi-outcome AI error: {e}")
        return None


# ─── Скоринг для multi-outcome ────────────────────────────────────────────────

def score_multi_outcome(outcomes_market: list[dict],
                         outcomes_ai: list[dict],
                         volume_24h: float,
                         news_age_hours: float,
                         confidence: str,
                         days_to_close: int) -> tuple[list[dict], int]:
    """
    Возвращает (scored_outcomes, best_score).
    scored_outcomes — список исходов с edge и индивидуальным скором.
    """
    # Матчим AI прогнозы к рыночным исходам по имени
    ai_map = {o["name"].lower(): o["probability"] for o in outcomes_ai}

    scored = []
    for o in outcomes_market:
        ai_prob = ai_map.get(o["name"].lower(), None)
        if ai_prob is None:
            # Пробуем частичное совпадение
            for ai_name, ai_p in ai_map.items():
                if ai_name[:4] in o["name"].lower() or o["name"].lower()[:4] in ai_name:
                    ai_prob = ai_p
                    break
        if ai_prob is None:
            continue

        market_prob_pct = o["market_prob"] * 100
        edge = ai_prob - market_prob_pct

        # Скор исхода
        score = 0
        abs_edge = abs(edge)
        if abs_edge >= 20:   score += 40
        elif abs_edge >= 15: score += 28
        elif abs_edge >= 10: score += 16
        elif abs_edge >= 7:  score += 8

        # News freshness
        if news_age_hours <= 1:    score += 12
        elif news_age_hours <= 3:  score += 8
        elif news_age_hours <= 6:  score += 5

        # Volume
        if volume_24h >= 50000:   score += 10
        elif volume_24h >= 10000: score += 6
        elif volume_24h >= 3000:  score += 3

        # Confidence penalty
        if confidence == "low":
            score = int(score * 0.5)

        # Time penalty
        if days_to_close < 2:
            score = int(score * 0.3)

        scored.append({
            "name": o["name"],
            "market_prob": market_prob_pct,
            "ai_prob": ai_prob,
            "edge": round(edge, 1),
            "direction": "UNDER" if edge > 0 else "OVER",  # рынок недо/переоценивает
            "score": score
        })

    best_score = max((o["score"] for o in scored), default=0)
    # Сортируем по абсолютному edge
    scored.sort(key=lambda x: abs(x["edge"]), reverse=True)
    return scored, best_score


# ─── Форматирование сигнала ───────────────────────────────────────────────────

def format_multi_signal(market: dict, scored_outcomes: list[dict],
                         analysis: dict, best_score: int) -> str:
    score_bar = "█" * (best_score // 10) + "░" * (10 - best_score // 10)

    # Таблица исходов
    outcome_lines = []
    for o in scored_outcomes:
        if abs(o["edge"]) < 5:
            continue  # пропускаем неинтересные

        arrow = "📈" if o["edge"] > 0 else "📉"
        highlight = " ◀ EDGE" if abs(o["edge"]) >= 10 else ""
        outcome_lines.append(
            f"{arrow} <b>{o['name']}</b>\n"
            f"   Рынок: {o['market_prob']:.1f}% → AI: {o['ai_prob']:.1f}% "
            f"(<b>{o['edge']:+.1f}%</b>){highlight}"
        )

    outcomes_block = "\n".join(outcome_lines) if outcome_lines else "Значимых расхождений нет"

    confidence_emoji = {"high": "💎", "medium": "⚡", "low": "💡"}.get(
        analysis.get("confidence", "medium"), "⚡"
    )

    return f"""
🎲 <b>MULTI-OUTCOME СИГНАЛ [{best_score}/100]</b>
{score_bar}

📋 <b>{market['question']}</b>

{outcomes_block}

{confidence_emoji} Уверенность: <b>{analysis.get('confidence','?').upper()}</b>

🔑 <b>Ключевой фактор:</b>
{analysis.get('key_factor', '—')}

🧠 <b>Анализ:</b>
{analysis.get('reasoning', '—')}

💰 Объём 24ч: <b>${market['volume_24h']:,.0f}</b> | До закрытия: <b>{market['days_to_close']} дн.</b>
🔗 <a href="{market['url']}">Открыть рынок</a>
""".strip()
