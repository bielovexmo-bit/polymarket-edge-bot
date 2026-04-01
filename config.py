import os
from dotenv import load_dotenv
load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# AI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# News
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Blockchain
POLYGONSCAN_API_KEY = os.getenv("POLYGONSCAN_API_KEY")

# Пороги
MIN_SCORE = 65              # Минимальный скор для сигнала
MIN_VOLUME = 3_000          # Минимальный объём рынка (ловим "забытые")
MAX_VOLUME_NEGLECTED = 20_000  # Потолок для "забытых" рынков
MIN_DAYS_TO_CLOSE = 2       # Не берём рынки которые вот-вот закроются
SCAN_INTERVAL = 60          # Секунд между сканами (реалтайм RSS)
SIGNAL_COOLDOWN_HOURS = 4   # Не дублируем сигнал по одному рынку
TOP_TRADERS_LIMIT = 100     # Сколько топ-трейдеров отслеживать
MIN_TRADER_PROFIT = 3_000   # Минимальная прибыль трейдера для попадания в список
