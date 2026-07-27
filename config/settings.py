SYMBOL = "BTC/USDT"

TIMEFRAMES = {
    "15M": "15m",
    "1H": "1h",
    "4H": "4h",
}

CANDLE_LIMIT = 1000

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200

RSI_PERIOD = 14

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

VOLUME_MA_PERIOD = 20

ATR_PERIOD = 14

# -------------------------
# Risk Management
# -------------------------

INITIAL_BALANCE = 10_000.0

RISK_PER_TRADE = 0.01

ATR_STOP_MULTIPLIER = 1.5

TAKE_PROFIT_RR = 2.0

MAX_HOLDING_CANDLES = 48

# -------------------------
# Futures Simulation
# -------------------------

LEVERAGE = 2.0

MAKER_FEE = 0.0002

TAKER_FEE = 0.0005

SLIPPAGE = 0.0002

FUNDING_RATE = 0.0001

FUNDING_INTERVAL_HOURS = 8

# Approximate maintenance margin

MAINTENANCE_MARGIN = 0.005

# -------------------------
# Backtest
# -------------------------

STARTING_CASH = INITIAL_BALANCE

ALLOW_LONG = True

ALLOW_SHORT = True