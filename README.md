# 🎯 Polymarket Edge Bot v3

Telegram-бот для поиска недооценённых рынков на Polymarket с AI-анализом, 
smart money трекингом и автокалибровкой.

## Фичи

- **AI Edge** — GPT-4o-mini оценивает истинную вероятность vs рыночную цену
- **Smart Money** — трекинг топ-трейдеров Polymarket по прибыли
- **Orderbook анализ** — давление покупки/продажи в стакане
- **Cross-market корреляции** — связанные рынки усиливают сигнал
- **Multi-outcome рынки** — отдельная логика для рынков с 3+ исходами
- **Бэктест** — калибровка на закрытых рынках перед запуском
- **Автотюнинг** — SQLite накапливает статистику, BIAS_CORRECTIONS корректируются автоматически
- **Telegram команды** — `/stats` `/accuracy` `/history`

## Быстрый старт

### 1. Клонировать репо
```bash
git clone https://github.com/bielovexmo-bit/polymarket-edge-bot
cd polymarket-edge-bot
```

### 2. Заполнить .env
```bash
cp .env.example .env
nano .env
```

### 3. Создать папку для БД
```bash
mkdir data
```

### 4. Бэктест (рекомендуется перед первым запуском)
```bash
pip install -r requirements.txt
python backtest.py
```

Бэктест прогонит ~300 закрытых рынков через AI, запишет результаты в SQLite
и откалибрует BIAS_CORRECTIONS. Занимает ~7-10 минут, стоит ~$0.15-0.20 на GPT.

### 5. Запуск через Docker
```bash
docker-compose up -d
docker-compose logs -f
```

## Структура проекта
```
polymarket-edge-bot/
├── main.py                  # Основной цикл
├── backtest.py              # Калибровка на исторических данных
├── config.py                # Конфиг и пороги
├── modules/
│   ├── polymarket.py        # Gamma API + CLOB API
│   ├── news.py              # RSS + NewsAPI
│   ├── wallet_tracker.py    # Smart money трекинг
│   ├── analyzer.py          # AI анализ (GPT-4o-mini)
│   ├── scorer.py            # Финальный скоринг
│   ├── telegram_bot.py      # Отправка сигналов + команды
│   ├── db.py                # SQLite: сигналы, volume, статистика
│   ├── tuner.py             # Автокалибровка BIAS
│   ├── stats.py             # Статистика для Telegram команд
│   └── multi_outcome.py     # Логика для рынков с 3+ исходами
├── data/
│   └── bias_corrections.json
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Переменные окружения

| Переменная | Описание | Обязательно |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather | ✅ |
| `TELEGRAM_CHAT_ID` | ID канала/чата для сигналов | ✅ |
| `OPENAI_API_KEY` | OpenAI API ключ (GPT-4o-mini) | ✅ |
| `NEWS_API_KEY` | NewsAPI.org ключ | ❌ |
| `POLYGONSCAN_API_KEY` | Polygonscan для on-chain данных | ❌ |

## Telegram команды

| Команда | Описание |
|---|---|
| `/stats` | Общая точность, кол-во сигналов, средний скор |
| `/accuracy` | Точность по категориям с прогресс-баром |
| `/history` | Последние 10 сигналов с исходами ✅/❌/⏳ |

## Скоринг

Максимум 120 очков (с бонусами), порог сигнала `MIN_SCORE = 65`.

| Фактор | Очки |
|---|---|
| AI Edge | 0-40 |
| Smart Money | 0-30 (+10 бонус за совпадение направления) |
| Volume Anomaly | 0-20 |
| News Freshness | 0-15 |
| Orderbook Signal | 0-10 |
| Cross-market бонус | +10 |

## Как работает автотюнинг

1. Каждый сигнал сохраняется в SQLite
2. Каждые 30 минут бот проверяет резолюции рынков
3. Раз в сутки `run_tuner()` пересчитывает BIAS_CORRECTIONS по реальной статистике
4. При накоплении 15+ резолюций на категорию — bias начинает корректироваться автоматически

## Disclaimer

Бот не является финансовым советником. Торгуй на собственный риск.
