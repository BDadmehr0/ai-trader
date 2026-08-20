SYMBOL = "BTC/USDT"

# Default quote currency for all pairs.
QUOTE = "USDT"

# Popular coins shown first in the top-bar switcher.
SUPPORTED_COINS = [
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "DOT",
    "LTC",
    "LINK",
    "AVAX",
    "MATIC",
    "TRX",
    "SHIB",
    "UNI",
    "ATOM",
    "XLM",
    "ETC",
    "FIL",
    "NEAR",
    "APT",
    "SUI",
    "ARB",
    "OP",
    "PEPE",
    "TON",
    "AAVE",
    "CRV",
    "INJ",
    "SEI",
    "WLD",
    "MEME",
]

TIMEFRAMES = {
    "15M": "15m",
    "1H": "1h",
    "4H": "4h",
}

CANDLE_LIMIT = 1000

# How many candles to send to the chart.
CHART_CANDLE_LIMIT = 400


# =========================
# Indicators
# =========================

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200

RSI_PERIOD = 14

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ATR_PERIOD = 14

VOLUME_MA_PERIOD = 20


# =========================
# Account
# =========================

INITIAL_BALANCE = 10_000.0


# =========================
# Risk
# =========================

RISK_PER_TRADE = 0.01

MAX_OPEN_POSITIONS = 1

COOLDOWN_CANDLES = 8


# =========================
# Stop / Target
# =========================

ATR_STOP_MULTIPLIER = 1.5

ATR_TP_MULTIPLIER = 3.0


# =========================
# Break Even
# =========================

ENABLE_BREAK_EVEN = True

BREAK_EVEN_R = 1.0

BREAK_EVEN_OFFSET = 0.0005


# =========================
# Trailing Stop
# =========================

ENABLE_TRAILING_STOP = True

TRAILING_ATR_MULTIPLIER = 1.5


# =========================
# Position
# =========================

LEVERAGE = 2.0


# =========================
# Fees
# =========================

TAKER_FEE = 0.0005

SLIPPAGE = 0.0002


# =========================
# Funding
# =========================

FUNDING_RATE = 0.0001

FUNDING_INTERVAL_HOURS = 8


# =========================
# Liquidation
# =========================

MAINTENANCE_MARGIN = 0.005


# =========================
# Strategy
# =========================

PULLBACK_DISTANCE = 0.015

MIN_VOLUME_RATIO = 1.1


# =========================
# Backtest
# =========================

MAX_HOLDING_CANDLES = 96