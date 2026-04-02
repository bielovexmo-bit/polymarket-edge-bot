from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from modules.stats import get_overall_stats, get_category_accuracy, get_last_signals


# ─── Команда /stats ───────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_overall_stats()
    accuracy = round(s["correct"] / max(s["resolved"], 1) * 100, 1)

    text = f"""
📊 <b>СТАТИСТИКА БОТА</b>

📨 Всего сигналов: <b>{s['total']}</b>
📅 За последние 24ч: <b>{s['today']}</b>
✅ Верных: <b>{s['correct']}</b>
❌ Неверных: <b>{s['incorrect']}</b>
🎯 Точность: <b>{accuracy}%</b>

⚡ Средний скор: <b>{s['avg_score']}/100</b>
🏆 Лучший скор: <b>{s['best_score']}/100</b>
🔍 Ожидают резолюции: <b>{s['resolved'] - s['correct'] - s['incorrect']}</b>
""".strip()

    await update.message.reply_text(text, parse_mode="HTML")


# ─── Команда /accuracy ────────────────────────────────────────────────────────

async def cmd_accuracy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = get_category_accuracy()
    if not cats:
        await update.message.reply_text("Недостаточно данных. Дождись резолюций рынков.")
        return

    lines = ["📈 <b>ТОЧНОСТЬ ПО КАТЕГОРИЯМ</b>\n"]
    for cat in cats:
        bar = "█" * int(cat["accuracy"] / 10) + "░" * (10 - int(cat["accuracy"] / 10))
        lines.append(
            f"<b>{cat['category']}</b>\n"
            f"{bar} {cat['accuracy']}%  ({cat['correct']}/{cat['total']})\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── Команда /history ─────────────────────────────────────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signals = get_last_signals(10)
    if not signals:
        await update.message.reply_text("Сигналов ещё нет.")
        return

    lines = ["📋 <b>ПОСЛЕДНИЕ 10 СИГНАЛОВ</b>\n"]
    for s in signals:
        if s["outcome"] == "correct":
            icon = "✅"
        elif s["outcome"] == "incorrect":
            icon = "❌"
        else:
            icon = "⏳"

        lines.append(
            f"{icon} [{s['score']}] {s['direction']} {s['edge_pct']:+.1f}%\n"
            f"<i>{s['question'][:55]}...</i>\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── Уведомление о резолюции (вызывается из main.py) ─────────────────────────

def send_resolution_notification(token: str, chat_id: str,
                                  question: str, direction: str,
                                  edge_pct: float, outcome: str, score: int):
    icon = "✅" if outcome == "correct" else "❌"
    result = "ВЕРНО" if outcome == "correct" else "НЕВЕРНО"

    text = f"""
{icon} <b>РЕЗОЛЮЦИЯ СИГНАЛА — {result}</b>

📋 {question[:80]}
🎯 Наш прогноз: <b>{direction}</b> ({edge_pct:+.1f}% edge)
📊 Скор сигнала: <b>{score}/100</b>
""".strip()

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10
    )


# ─── Запуск Telegram-бота с командами (в отдельном треде) ────────────────────

def start_command_bot(token: str):
    """Запускается в отдельном потоке параллельно основному циклу"""
    import asyncio
    from threading import Thread

    def run():
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("stats", cmd_stats))
        app.add_handler(CommandHandler("accuracy", cmd_accuracy))
        app.add_handler(CommandHandler("history", cmd_history))
        app.run_polling(drop_pending_updates=True)

    t = Thread(target=run, daemon=True)
    t.start()
```

---

Обновляем **`requirements.txt`** — добавить:
```
python-telegram-bot>=20.0
