"""
Single source of truth for every tunable setting of AI Trader.

Each item defines: type, default value, validation range and UI metadata, so
the same definition is used for

* the runtime settings store  (config/store.py)
* the web settings page       (webapp → /settings)
* the CLI (`python main.py settings --show`)
* the backtest optimizer (which params may be searched)

Adding a new setting = adding one Item here + reading it where it belongs.
Nothing else has to know about it.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Item:
    """One configurable value."""

    key: str
    label: str
    default: Any
    type: str = "float"          # str | text | int | float | bool | list | dict | enum
    help: str = ""               # short hint shown in the UI (Persian)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: tuple = ()
    secret: bool = False
    unit: str = ""
    optimizer: bool = False      # eligible for backtest parameter search


@dataclass(frozen=True)
class Group:
    """A UI section / form tab."""

    id: str
    label: str
    label_fa: str
    icon: str
    items: tuple


# =====================================================================
# 1. Data source
# =====================================================================

DATA_GROUP = Group(
    id="data",
    label="Data",
    label_fa="داده‌ها",
    icon="🗄",
    items=(
        Item("symbol", "Default symbol", "BTC/USDT", type="str",
             help="نماد پیش‌فرض که داشبورد با آن باز می‌شود."),
        Item("quote", "Quote currency", "USDT", type="str",
             help="ارز مبنای جفت‌ها در سوییچر بالای صفحه."),
        Item("exchange_id", "Exchange id (ccxt)", "binance", type="str",
             help="هر صرافی که ccxt پشتیبانی می‌کند: binance, kucoin, bybit, okx ..."),
        Item("proxy_url", "Proxy url", "", type="str",
             help="در صورت نیاز به فیلترشکن: http://127.0.0.1:7890"),
        Item("data_source", "Data source", "auto", type="enum",
             choices=("auto", "exchange", "csv", "demo"),
             help="auto = اول صرافی، اگر نشد CSV/دمو — csv = فقط داده‌ی خودت."),
        Item("csv_path", "My data: CSV path", "", type="str",
             help="مسیر فایل CSV شمع‌های خودت (timestamp, open, high, low, close, volume)."),
        Item("csv_timeframe", "CSV native timeframe", "15m", type="str",
             help="تایم‌فریم واقعی فایل CSV؛ بقیه‌ی تایم‌فریم‌ها از روی آن ساخته می‌شوند."),
        Item("timeframes", "Timeframes (base, mid, higher)", "15m,1h,4h", type="str",
             help="سه تایم‌فریمی که تحلیل روی آن‌ها انجام می‌شود."),
        Item("candle_limit", "Candles to fetch", 1000, type="int", min=200, max=1500, step=50,
             help="تعداد کندل خام برای هر تایم‌فریم."),
        Item("chart_candle_limit", "Candles on chart", 400, type="int", min=50, max=1000, step=50),
        Item("cache_minutes", "Data cache TTL (minutes)", 2, type="int", min=0, max=240,
             help="چند دقیقه داده‌ی هر نماد کش شود تا API دایم زده نشود. ۰ = بدون کش."),
        Item("supported_coins", "Coin switcher list", [
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT", "LTC", "LINK",
            "AVAX", "TRX", "UNI", "ATOM", "XLM", "ETC", "FIL", "NEAR", "APT", "SUI",
            "ARB", "OP", "TON", "AAVE", "INJ", "SEI",
        ], type="list", help="لیست ارزهای نوار بالا (JSON array یا خط‌به‌خط)."),
    ),
)


# =====================================================================
# 2. Indicators
# =====================================================================

INDICATOR_GROUP = Group(
    id="indicators",
    label="Indicators",
    label_fa="اندیکاتورها",
    icon="📈",
    items=(
        Item("ema_fast", "EMA fast", 20, type="int", min=2, max=120),
        Item("ema_mid", "EMA mid", 50, type="int", min=3, max=300),
        Item("ema_slow", "EMA slow", 200, type="int", min=5, max=500),
        Item("rsi_period", "RSI period", 14, type="int", min=2, max=100, optimizer=True),
        Item("rsi_overbought", "RSI overbought", 70, type="float", min=55, max=95, step=1),
        Item("rsi_oversold", "RSI oversold", 30, type="float", min=5, max=45, step=1),
        Item("macd_fast", "MACD fast", 12, type="int", min=2, max=60),
        Item("macd_slow", "MACD slow", 26, type="int", min=3, max=120),
        Item("macd_signal", "MACD signal", 9, type="int", min=2, max=60),
        Item("atr_period", "ATR period", 14, type="int", min=2, max=100, optimizer=True),
        Item("volume_ma_period", "Volume MA period", 20, type="int", min=2, max=200),
        Item("adx_period", "ADX period", 14, type="int", min=5, max=60,
             help="قدرت روند؛ زیر این عدد بازار رِنج است و سیگنال‌ها فیلتر می‌شوند."),
        Item("adx_trend_min", "ADX trend minimum", 20, type="float", min=0, max=60, step=1,
             optimizer=True),
        Item("bb_period", "Bollinger period", 20, type="int", min=5, max=140),
        Item("bb_std", "Bollinger std", 2.0, type="float", min=1.0, max=4.0, step=0.1),
        Item("stoch_rsi_period", "Stochastic RSI period", 14, type="int", min=2, max=60),
        Item("mfi_period", "MFI period", 14, type="int", min=2, max=60),
        Item("cci_period", "CCI period", 20, type="int", min=5, max=100),
        Item("supertrend_period", "SuperTrend period", 10, type="int", min=3, max=60,
             help="خط روند بر پایه‌ی ATR؛ یکی از مطمئن‌ترین فیلترهای روند."),
        Item("supertrend_multiplier", "SuperTrend multiplier", 3.0, type="float",
             min=1.0, max=6.0, step=0.1, optimizer=True),
        Item("vwap_session", "VWAP anchor", "daily", type="enum",
             choices=("daily", "weekly", "none"),
             help="VWAP سازمانی: فاصله‌ی قیمت از میانگین حجمی-وزنی روز."),
        Item("obv_slope_period", "OBV slope lookback", 10, type="int", min=3, max=60),
    ),
)


# =====================================================================
# 3. Strategy rules
# =====================================================================

STRATEGY_GROUP = Group(
    id="strategy",
    label="Strategy",
    label_fa="استراتژی",
    icon="🎯",
    items=(
        Item("entry_threshold", "Entry score threshold", 35, type="float", min=5, max=95, step=1,
             help="ترکیب امتیازات باید از این عدد عبور کند تا LONG/SHORT صادر شود.",
             optimizer=True),
        Item("neutral_threshold", "No-trade threshold", 10, type="float", min=0, max=40, step=1,
             help="زیر این مطلق امتیاز، بازار بدون معامله اعلام می‌شود."),
        Item("min_confidence", "Minimum confidence", 45, type="int", min=0, max=95, step=1,
             help="اگر اطمینان کمتر از این باشد سیگنال به WAIT تبدیل می‌شود.",
             optimizer=True),
        Item("require_trend_alignment", "Timeframes that must agree", 2, type="int", min=1, max=3,
             help="چند تایم‌فریم باید هم‌جهت روند باشند (۲ از ۳ معمولاً تعادل خوبی است)."),
        Item("require_macd_cross", "Require MACD confirmation", True, type="bool",
             help="فقط با تأیید کراس/هيستوگرام MACD وارد شو."),
        Item("require_volume_confirm", "Require volume confirmation", True, type="bool",
             help="ورود بدون حجم تأییدشده ممنوع."),
        Item("require_structure_agreement", "Reject structure conflict", True, type="bool",
             help="اگر ساختار HH/HL با جهت معامله می‌جنگد، سیگنال رد شود."),
        Item("allow_longs", "Allow LONG signals", True, type="bool"),
        Item("allow_shorts", "Allow SHORT signals", True, type="bool"),
        Item("pullback_distance", "Pullback distance to EMA", 0.015, type="float",
             min=0.0, max=0.1, step=0.001,
             help="حداکثر فاصله‌ی قیمت از EMA برای «پولبک» محسوب شدن.", optimizer=True),
        Item("min_volume_ratio", "Min volume ratio", 1.1, type="float", min=0.0, max=5.0,
             step=0.05, optimizer=True),
        Item("rsi_long_min", "RSI floor for LONG", 40, type="float", min=0, max=100, step=1),
        Item("rsi_long_max", "RSI ceiling for LONG", 68, type="float", min=0, max=100, step=1,
             help="خرید در RSI خیلی بالا معمولاً تعقیب قیمت است، نه ورود."),
        Item("rsi_short_min", "RSI floor for SHORT", 32, type="float", min=0, max=100, step=1),
        Item("rsi_short_max", "RSI ceiling for SHORT", 60, type="float", min=0, max=100, step=1),
        Item("max_overextension_pct", "Max overextension %", 3.5, type="float", min=0.5, max=30.0,
             step=0.1, help="اگر قیمت از EMA بیشتر از این درصد فاصله داشت، وارد نشو (چیزینگ)."),
        Item("max_atr_ratio", "Max ATR vs its average", 2.2, type="float", min=1.0, max=8.0,
             step=0.1, help="نوسان بیش از این چند برابر میانگین = بازار در حالت شوک؛ ورود ممنوع."),
        Item("min_bars_between_signals", "Cooldown between signals", 8, type="int", min=0, max=200,
             step=1),
    ),
)


# =====================================================================
# 4. Scoring weights
# =====================================================================

SCORING_GROUP = Group(
    id="scoring",
    label="Scoring weights",
    label_fa="وزن تحلیل‌ها",
    icon="⚖️",
    items=(
        Item("weight_trend", "Trend", 25, type="float", min=0, max=60, step=1, optimizer=True),
        Item("weight_momentum", "Momentum", 20, type="float", min=0, max=60, step=1,
             optimizer=True),
        Item("weight_volume", "Volume", 15, type="float", min=0, max=60, step=1, optimizer=True),
        Item("weight_structure", "Market structure", 15, type="float", min=0, max=60, step=1,
             optimizer=True),
        Item("weight_alignment", "Timeframe alignment", 15, type="float", min=0, max=60,
             step=1, optimizer=True),
        Item("weight_volatility", "Volatility regime", 5, type="float", min=0, max=60, step=1),
        Item("weight_levels", "Support / resistance", 5, type="float", min=0, max=60, step=1),
        Item("weight_news", "News & AI sentiment", 12, type="float", min=0, max=60, step=1,
             help="اخبار + خروجی مدل AI محلی. اگر منبعی آفلاین بود وزنش حذف می‌شود."),
        Item("weight_derivatives", "Derivatives / funding", 8, type="float", min=0, max=60,
             step=1, help="فاندینگ، بازفتح معامله و نسبت لانگ/شورت."),
        Item("weight_micro", "Order book micro", 6, type="float", min=0, max=60, step=1,
             help="عدم تعادل سفارش‌ها در عمق بازار و اسپرد."),
        Item("weight_cross_asset", "BTC regime / correlation", 6, type="float", min=0, max=60,
             step=1, help="برای آلت‌کوین‌ها: هم‌بستگی و جهت کلی بازار."),
        Item("weight_mode", "Weight mode", "manual", type="enum", choices=("manual", "adaptive"),
             help="adaptive: وزن‌ها با توجه به نتیجه‌ی سیگنال‌های گذشته خودکار تنظیم می‌شوند."),
        Item("adaptive_min_samples", "Adaptive: min samples", 30, type="int", min=10, max=500,
             step=5, help="تا این تعداد سیگنال ثبت‌شده ارزیابی نشده باشد، حالت adaptive اثر نمی‌کند."),
        Item("confidence_penalty_missing_data", "Penalty for missing data", True, type="bool",
             help="اگر داده‌ای (اخبار/فوتچرز) در دسترس نبود، اطمینان کمی پایین می‌آید."),
    ),
)


# =====================================================================
# 5. News + local AI sentiment
# =====================================================================

NEWS_GROUP = Group(
    id="news",
    label="News & AI sentiment",
    label_fa="اخبار و هوش مصنوعی",
    icon="📰",
    items=(
        Item("news_enabled", "Enable news analysis", True, type="bool",
             help="خاموش = تحلیل فقط تکنیکال."),
        Item("news_provider", "Sentiment engine", "lexicon", type="enum",
             choices=("ollama", "openai", "lexicon", "off"),
             help="ollama = مدل محلی شما، openai = هر endpoint سازگار (LM Studio/vLLM/OpenAI)، "
                  "lexicon = موتور آفلاین داخلی."),
        Item("ollama_url", "Ollama url", "http://127.0.0.1:11434", type="str"),
        Item("ollama_model", "Ollama model", "llama3.1", type="str",
             help="مدلی که نصب کرده‌اید: ollama pull llama3.1"),
        Item("openai_base_url", "OpenAI-compatible base url", "https://api.openai.com/v1",
             type="str", help="برای LM Studio: http://127.0.0.1:1234/v1"),
        Item("openai_model", "Model name", "gpt-4o-mini", type="str"),
        Item("openai_api_key", "API key", "", type="str", secret=True,
             help="می‌توانید در .env also AI_TRADER_OPENAI_API_KEY بگذارید."),
        Item("llm_timeout", "LLM timeout (s)", 45, type="int", min=5, max=600, step=5),
        Item("llm_temperature", "LLM temperature", 0.0, type="float", min=0.0, max=1.0, step=0.1),
        Item("llm_batch_size", "Headlines per request", 12, type="int", min=1, max=30),
        Item("llm_max_tokens", "Max tokens per request", 700, type="int", min=64, max=4096,
             step=32),
        Item("rss_feeds", "RSS feeds", [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://decrypt.co/feed",
            "https://bitcoinmagazine.com/.rss/full/",
        ], type="list", help="فیدهای خبری که اسکن می‌شوند (یک آدرس در هر خط)."),
        Item("news_max_headlines", "Max headlines to scan", 40, type="int", min=5, max=200,
             step=5),
        Item("news_min_items", "Min items to trust", 3, type="int", min=1, max=30),
        Item("news_http_timeout", "News http timeout (s)", 8, type="int", min=2, max=60),
        Item("news_cache_ttl", "News cache (s)", 900, type="int", min=60, max=86400, step=60,
             help="چند ثانیه نتیجه‌ی اخبار کش شود (مصرف API و سرعت صفحه)."),
        Item("recency_half_life_hours", "Headline half-life (h)", 18, type="float", min=1,
             max=168, step=1, help="هرچه خبر قدیمی‌تر، وزنش نمایی کمتر می‌شود."),
        Item("symbol_relevance_only", "Only symbol-relevant news", True, type="bool",
             help="خاموش = خبرهای کلان بازار هم در امتیاز اثر دارند."),
        Item("cryptopanic_enabled", "CryptoPanic source", False, type="bool",
             help="نیاز به توکن رایگان از cryptopanic.com/developers/api"),
        Item("cryptopanic_token", "CryptoPanic token", "", type="str", secret=True),
        Item("fear_greed_enabled", "Fear & Greed index", True, type="bool",
             help="شاخص ترس و طمع alternative.me — یک داده‌ی رفتاری رایگان و بدون کلید."),
        Item("fear_greed_weight", "Fear & Greed weight in news", 20, type="float", min=0,
             max=100, step=5),
        Item("news_veto_mode", "Extreme-news guard", "downgrade", type="enum",
             choices=("off", "downgrade", "block"),
             help="block: اخبار خیلی بد = هیچ معامله‌ای؛ downgrade: آستانه‌ی ورود سخت‌تر."),
        Item("news_veto_threshold", "Veto |sentiment|", 0.55, type="float", min=0.1, max=0.95,
             step=0.05),
        Item("news_extra_keywords", "Extra coin aliases", {}, type="dict",
             help='نگاشت نماد به کلمات کلیدی، مثال: {"SUI": ["sui", "move network"]}'),
    ),
)


# =====================================================================
# 6. Derivatives & microstructure
# =====================================================================

DERIV_GROUP = Group(
    id="derivatives",
    label="Derivatives & microstructure",
    label_fa="فوتچرز و ساختار بازار",
    icon="🧪",
    items=(
        Item("derivatives_enabled", "Use funding / open interest", True, type="bool",
             help="داده‌ی عمومی Binance Futures بدون کلید API."),
        Item("futures_base_url", "Futures api base url", "https://fapi.binance.com", type="str"),
        Item("derivatives_http_timeout", "Timeout (s)", 6, type="int", min=2, max=60),
        Item("derivatives_cache_ttl", "Cache (s)", 120, type="int", min=15, max=3600, step=15),
        Item("funding_extreme", "Extreme funding rate", 0.0005, type="float", min=0.00005,
             max=0.01, step=0.00005,
             help="فاندینگ بالای این = خریداران بیش‌ازحد هیجانی (ریسک ریزش)."),
        Item("funding_crowded", "Crowded funding rate", 0.00015, type="float", min=0.0,
             max=0.005, step=0.00005),
        Item("oi_lookback_hours", "Open-interest lookback (h)", 12, type="int", min=1, max=72),
        Item("oi_strong_change", "Strong OI change", 0.04, type="float", min=0.005, max=0.5,
             step=0.005),
        Item("ls_ratio_extreme", "Extreme long/short account ratio", 2.6, type="float", min=1.0,
             max=6.0, step=0.1, help="نسبت خیلی بالا = شورت‌اسکوییز/ریسک اصلاح."),
        Item("micro_enabled", "Order-book microstructure", True, type="bool",
             help="عدم تعادل bid/ask و اسپرد لحظه‌ای."),
        Item("order_book_depth", "Order book levels", 60, type="int", min=5, max=500, step=5),
        Item("max_spread_pct", "Max acceptable spread %", 0.06, type="float", min=0.001,
             max=2.0, step=0.001, help="اسپرد بالاتر = نقدشوندگی بد → رد سیگنال."),
        Item("min_quote_volume_24h", "Min 24h volume (quote)", 3_000_000, type="float",
             min=0, max=1e10,
             help="حجم ۲۴ ساعته‌ی کمتر از این = بازار غیرقابل‌اعتماد برای اسلیپیج."),
        Item("cross_asset_enabled", "BTC regime filter", True, type="bool",
             help="برای آلت‌کوین‌ها: خلاف جهت BTC وارد نشو."),
        Item("cross_asset_lookback", "Correlation lookback (candles)", 96, type="int", min=20,
             max=500, step=4),
        Item("cross_asset_timeframe", "Cross-asset timeframe", "4h", type="str"),
        Item("cross_asset_corr_min", "Min correlation to act", 0.4, type="float", min=0.0,
             max=0.95, step=0.05),
    ),
)


# =====================================================================
# 7. Risk & trade management
# =====================================================================

RISK_GROUP = Group(
    id="risk",
    label="Risk & management",
    label_fa="ریسک و مدیریت معامله",
    icon="🛡",
    items=(
        Item("initial_balance", "Account balance", 10_000.0, type="float", min=10.0,
             max=1e9, step=100),
        Item("risk_per_trade", "Risk per trade", 0.01, type="float", min=0.0005, max=0.5,
             step=0.001, unit="fraction",
             help="۰.۰۱ یعنی یک درصد سرمایه در هر معامله."),
        Item("max_open_positions", "Max open positions", 1, type="int", min=1, max=20),
        Item("leverage", "Leverage", 2.0, type="float", min=1.0, max=50.0, step=0.5),
        Item("stop_mode", "Stop-loss mode", "hybrid", type="enum",
             choices=("atr", "structure", "hybrid"),
             help="structure = زیر آخرین دره/قله؛ hybrid = امن‌ترِ هر دو."),
        Item("atr_stop_multiplier", "ATR stop multiplier", 1.5, type="float", min=0.3, max=6.0,
             step=0.1, optimizer=True),
        Item("stop_structure_buffer", "Structure stop buffer (ATR)", 0.25, type="float", min=0.0,
             max=2.0, step=0.05),
        Item("target_mode", "Target mode", "atr", type="enum", choices=("atr", "structure", "rr"),
             help="rr = فقط تا جایی که نسبت ریسک به ریوارد مجاز باشد."),
        Item("tp1_r", "TP1 (R multiple)", 1.5, type="float", min=0.2, max=10.0, step=0.1,
             optimizer=True),
        Item("tp2_r", "TP2 (R multiple)", 2.5, type="float", min=0.3, max=20.0, step=0.1,
             optimizer=True),
        Item("atr_tp_multiplier", "ATR target multiplier", 3.0, type="float", min=0.5, max=10.0,
             step=0.1),
        Item("min_risk_reward", "Min R:R to take trade", 1.3, type="float", min=0.0, max=5.0,
             step=0.05, help="اگر مقاومت جلوی TP را گرفته و R:R کم شد، سیگنال رد می‌شود."),
        Item("enable_break_even", "Move to break even", True, type="bool"),
        Item("break_even_r", "Break-even trigger (R)", 1.0, type="float", min=0.1, max=5.0,
             step=0.1),
        Item("break_even_offset", "Break-even offset", 0.0005, type="float", min=0.0, max=0.01,
             step=0.0001),
        Item("enable_trailing_stop", "ATR trailing stop", True, type="bool"),
        Item("trailing_atr_multiplier", "Trailing ATR multiplier", 1.5, type="float", min=0.3,
             max=6.0, step=0.1, optimizer=True),
        Item("taker_fee", "Taker fee", 0.0005, type="float", min=0.0, max=0.02, step=0.0001),
        Item("slippage", "Slippage", 0.0002, type="float", min=0.0, max=0.02, step=0.0001),
        Item("funding_rate", "Funding rate (per interval)", 0.0001, type="float", min=-0.01,
             max=0.01, step=0.0001),
        Item("funding_interval_hours", "Funding interval (h)", 8, type="int", min=1, max=24),
        Item("maintenance_margin", "Maintenance margin", 0.005, type="float", min=0.0, max=0.2,
             step=0.001),
        Item("max_holding_candles", "Max holding (candles)", 96, type="int", min=1, max=2000,
             step=1, optimizer=True),
        Item("cooldown_candles", "Cooldown (candles)", 8, type="int", min=0, max=200),
    ),
)


# =====================================================================
# 8. Signal journal / self-calibration
# =====================================================================

JOURNAL_GROUP = Group(
    id="journal",
    label="Signal journal",
    label_fa="دفترچه‌ی سیگنال‌ها",
    icon="📓",
    items=(
        Item("journal_enabled", "Record every signal", True, type="bool",
             help="هر سیگنال با امتیاز اجزا در data/logs/signals.jsonl ثبت می‌شود."),
        Item("journal_eval_after_candles", "Judge outcome after (candles)", 12, type="int",
             min=1, max=240,
             help="چند کندل بعد، نتیجه‌ی معامله (TP/SL اول) شبیه‌سازی و ثبت می‌شود."),
        Item("journal_touch_tolerance", "TP/SL touch mode", "strict", type="enum",
             choices=("strict", "conservative"),
             help="conservative = اگر کندل هم TP و هم SL را دید، ضرر ثبت می‌شود."),
        Item("journal_path", "Journal file", "data/logs/signals.jsonl", type="str"),
    ),
)


# =====================================================================
# 9. Backtest & optimizer
# =====================================================================

BACKTEST_GROUP = Group(
    id="backtest",
    label="Backtest & optimizer",
    label_fa="بک‌تست و بهینه‌ساز",
    icon="🧮",
    items=(
        Item("backtest_candles", "Backtest candles", 1000, type="int", min=100, max=1500,
             step=100),
        Item("optimizer_trials", "Trials per run", 18, type="int", min=2, max=200, step=1),
        Item("optimizer_mode", "Search mode", "random", type="enum", choices=("grid", "random")),
        Item("optimizer_objective", "Objective", "score", type="enum",
             choices=("score", "sharpe", "profit_factor", "total_return", "win_rate"),
             help="score = ترکیب بازده، شارپ، فکتور ضرر و تعداد معامله (پیش‌فرض توصیه‌شده)."),
        Item("optimizer_ranges", "Param ranges", {}, type="dict",
             help='مثال: {"entry_threshold": [25, 30, 35, 40], "atr_stop_multiplier": [1.2, 1.5, 2.0]}'),
        Item("optimizer_train_ratio", "Train / test split", 0.7, type="float", min=0.3, max=0.9,
             step=0.05, help="برای جلوگیری از اورفیت، بهترین پارامتر روی ۷۰٪ اول انتخاب می‌شود."),
        Item("optimizer_seed", "Random seed", 7, type="int", min=0, max=99999),
    ),
)


# =====================================================================
# 10. Interface
# =====================================================================

UI_GROUP = Group(
    id="ui",
    label="Interface",
    label_fa="رابط کاربری",
    icon="🎛",
    items=(
        Item("ui_language", "Language", "fa", type="enum", choices=("fa", "en")),
        Item("ui_refresh_seconds", "Dashboard auto refresh (s)", 60, type="int", min=0,
             max=900, step=15, help="۰ = خاموش."),
        Item("ui_show_persian_help", "Show Persian hints in settings", True, type="bool"),
        Item("ui_show_reasoning", "Show analysis reasoning panel", True, type="bool"),
        Item("ui_chart_overlay_bb", "Chart: Bollinger overlay", True, type="bool"),
        Item("ui_chart_overlay_vwap", "Chart: VWAP overlay", True, type="bool"),
        Item("ui_chart_overlay_supertrend", "Chart: SuperTrend overlay", True, type="bool"),
        Item("ui_chart_overlay_ema", "Chart: EMA overlay", True, type="bool"),
    ),
)


GROUPS = (
    DATA_GROUP,
    INDICATOR_GROUP,
    STRATEGY_GROUP,
    SCORING_GROUP,
    NEWS_GROUP,
    DERIV_GROUP,
    RISK_GROUP,
    JOURNAL_GROUP,
    BACKTEST_GROUP,
    UI_GROUP,
)

ITEMS = {item.key: item for group in GROUPS for item in group.items}
DEFAULTS = {key: item.default for key, item in ITEMS.items()}

OPTIMIZABLE = tuple(key for key, item in ITEMS.items() if item.optimizer)


def ui_groups():
    """Groups serialized for the settings page / schema endpoint."""
    out = []
    for group in GROUPS:
        out.append({
            "id": group.id,
            "label": group.label,
            "label_fa": group.label_fa,
            "icon": group.icon,
            "items": [
                {
                    "key": it.key,
                    "label": it.label,
                    "help": it.help,
                    "type": it.type,
                    "default": it.default,
                    "min": it.min,
                    "max": it.max,
                    "step": it.step,
                    "choices": list(it.choices),
                    "secret": it.secret,
                    "unit": it.unit,
                    "optimizer": it.optimizer,
                }
                for it in group.items
            ],
        })
    return out
