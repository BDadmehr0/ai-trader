"""
Market data access.

Three interchangeable sources, chosen in the settings page:

* ``exchange`` — live candles through ccxt (Binance by default)
* ``csv``      — your own exported candles (data/csv_source.py)
* ``demo``     — bundled synthetic data, so the app runs with no internet
* ``auto``     — try the exchange, fall back to CSV if configured, else demo

Every source is normalised to the same canonical OHLCV frame, results are
cached for ``cache_minutes``, and ``last_error`` / ``source`` tell the UI
exactly where the numbers came from — an analysis that silently switches to
fake data would be worse than one that fails loudly.
"""

import logging
import os

import pandas as pd
from dotenv import load_dotenv

from config.store import get_settings
from data.csv_source import load_csv, profile as csv_profile, resample, timeframe_minutes
from data.demo import ensure_demo_data, load_demo
from utils.cache import cache_for

load_dotenv()

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "ohlcv"
NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


def _rows_for_cache(frame: pd.DataFrame):
    """Timestamps → epoch seconds so the JSON cache can actually store them."""
    out = []
    for row in frame.to_dict("records"):
        stamp = row.get("timestamp")
        if stamp is None:
            continue
        try:
            row["timestamp"] = float(pd.Timestamp(stamp).timestamp())
        except (TypeError, ValueError):
            row["timestamp"] = None
        out.append(row)
    return out


def _frame_from_rows(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(pd.to_numeric(frame["timestamp"], errors="coerce"),
                                            unit="s", utc=True)
    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


class MarketData:
    """OHLCV / ticker provider with transparent fallbacks."""

    def __init__(self, exchange_id=None, settings=None, source=None):
        self.settings = settings or get_settings()
        self._exchange_id = exchange_id or os.getenv("EXCHANGE_ID") or self.settings.exchange_id
        self._requested_source = (source or self.settings.data_source or "auto").lower()
        self._exchange = None
        self._exchange_error = None

        self._source = "demo" if self._requested_source == "demo" else (
            "csv" if self._requested_source == "csv" else "exchange")
        self._live = self._source == "exchange"
        self._last_error = None
        self._fallback_logged = False

        self._csv_frame = None
        self._csv_error = None
        if self._requested_source in ("csv", "auto") and self.settings.csv_path:
            self._load_csv()

    # =================================================================
    # state
    # =================================================================
    @property
    def is_live(self):
        return self._live

    @property
    def source(self):
        return self._source

    @property
    def last_error(self):
        return self._last_error

    def describe(self):
        return {
            "requested": self._requested_source,
            "used": self._source,
            "live": self._live,
            "exchange": self._exchange_id,
            "csv_path": self.settings.csv_path or None,
            "csv_error": self._csv_error,
            "error": self._last_error,
        }

    # =================================================================
    # exchange
    # =================================================================
    @property
    def exchange(self):
        if self._exchange is None and self._exchange_error is None:
            self._exchange = self._build_exchange()
        return self._exchange

    def _build_exchange(self):
        import ccxt

        config = {
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {"defaultType": "spot"},
        }
        proxy_url = os.getenv("PROXY_URL") or self.settings.proxy_url
        if proxy_url:
            config["proxies"] = {"http": proxy_url, "https": proxy_url}

        try:
            return getattr(ccxt, self._exchange_id)(config)
        except Exception as exc:  # noqa: BLE001 - unknown id, ccxt import issue, ...
            self._exchange_error = f"{exc.__class__.__name__}: {exc}"
            logger.warning("exchange %s unavailable (%s)", self._exchange_id, exc)
            return None

    # =================================================================
    # user CSV
    # =================================================================
    def _load_csv(self):
        try:
            frame = load_csv(self.settings.csv_path, self.settings.csv_timeframe)
            self._csv_frame = frame
            self._csv_error = None
        except Exception as exc:  # noqa: BLE001
            self._csv_frame = None
            self._csv_error = str(exc)[:300]
            logger.warning("csv source failed: %s", self._csv_error)

    @property
    def csv_timeframe(self):
        if self._csv_frame is None:
            return None
        return self._csv_frame.attrs.get("timeframe") or self.settings.csv_timeframe

    def csv_profile(self):
        if not self.settings.csv_path:
            return {"ok": False, "error": "no csv configured"}
        return csv_profile(self.settings.csv_path, self.settings.csv_timeframe)

    # =================================================================
    # candles
    # =================================================================
    def get_ohlcv(self, symbol, timeframe=None, limit=None):
        """Canonical OHLCV frame (live, csv or demo — never raises)."""
        settings = self.settings
        timeframe = timeframe or settings.tf_mid
        limit = int(limit or settings.candle_limit)

        cache = cache_for(CACHE_NAMESPACE)
        ttl = max(0.0, float(settings.cache_minutes) * 60.0)
        key = f"{self._requested_source}:{symbol}:{timeframe}:{limit}"

        if ttl > 0:
            cached = cache.read_fresh(key, ttl)
            if isinstance(cached, dict) and cached.get("rows"):
                frame = _frame_from_rows(cached["rows"])
                self._source = cached.get("source", self._source)
                self._live = self._source == "exchange"
                return frame

        frame = None
        if self._requested_source != "demo":
            frame = self._fetch_csv(symbol, timeframe, limit)
            if frame is not None:
                self._source = "csv"
                self._live = False
            if frame is None and self._requested_source in ("exchange", "auto"):
                frame = self._fetch_live(symbol, timeframe, limit)
                if frame is not None:
                    self._source = "exchange"
                    self._live = True

        if frame is None:
            frame = self._fetch_demo(symbol, timeframe, limit)
            if frame is not None:
                self._source = "demo"
                self._live = False

        if frame is None:
            raise RuntimeError(f"no data available for {symbol} {timeframe}: {self._last_error}")

        if ttl > 0 and len(frame):
            cache.write(key, {"rows": _rows_for_cache(frame), "source": self._source})
        return frame

    def _fetch_live(self, symbol, timeframe, limit):
        exchange = self.exchange
        if exchange is None:
            self._last_error = self._exchange_error or "exchange unavailable"
            return None
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not data:
                raise RuntimeError("empty candle response")

            frame = pd.DataFrame(data, columns=["timestamp", *NUMERIC_COLUMNS])
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
            for column in NUMERIC_COLUMNS:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna(subset=["close"]).reset_index(drop=True)

            self._last_error = None
            return frame
        except Exception as exc:  # noqa: BLE001 - geo-block, rate limit, offline, ...
            self._last_error = str(exc)[:300]
            self._note_fallback(exc)
            return None

    def _fetch_csv(self, symbol, timeframe, limit):
        if self._csv_frame is None:
            return None
        try:
            frame = resample(self._csv_frame, timeframe, source_timeframe=self.csv_timeframe)
        except ValueError as exc:
            self._last_error = str(exc)
            logger.info("csv cannot provide %s: %s", timeframe, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            return None

        if limit and len(frame) > limit:
            frame = frame.tail(limit).reset_index(drop=True)
        self._last_error = None
        return frame

    def _fetch_demo(self, symbol, timeframe, limit):
        try:
            ensure_demo_data(symbol=symbol)
            frame = load_demo(timeframe, symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"demo data failed: {exc}"
            return None
        if limit and len(frame) > limit:
            frame = frame.tail(limit).reset_index(drop=True)
        return frame

    def _note_fallback(self, exc):
        if self._fallback_logged:
            return
        self._fallback_logged = True
        logger.warning(
            "Live data unavailable (%s). Falling back to %s — results are NOT real market prices.",
            exc, "csv" if self._csv_frame is not None else "demo data",
        )

    # =================================================================
    # ticker / book
    # =================================================================
    def get_ticker(self, symbol):
        """Latest price + 24h stats, derived from candles when offline."""
        if self._live and self.exchange is not None:
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                info = ticker.get("info") or {}
                quote_volume = info.get("quoteVolume") or info.get("volume")
                return {
                    "last": ticker.get("last"),
                    "change_pct": ticker.get("percentage"),
                    "high": ticker.get("high"),
                    "low": ticker.get("low"),
                    "base_volume": ticker.get("baseVolume"),
                    "quote_volume": float(quote_volume) if quote_volume else None,
                    "source": "exchange",
                }
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)[:200]
        return self._ticker_from_candles(symbol)

    def _ticker_from_candles(self, symbol):
        try:
            frame = self.get_ohlcv(symbol, self.settings.tf_base, max(96, int(self.settings.candle_limit) // 4))
        except Exception:  # noqa: BLE001
            return None
        if frame is None or frame.empty:
            return None

        minutes = timeframe_minutes(self.settings.tf_base)
        window = max(1, int(24 * 60 / minutes))
        recent = frame.tail(window)
        first = float(recent["close"].iloc[0])
        last = float(recent["close"].iloc[-1])
        quote_volume = None
        if "quote_volume" in frame.columns:
            quote_volume = float(recent["quote_volume"].tail(window).sum())
        else:
            try:
                quote_volume = float((recent["volume"] * recent["close"]).sum())
            except Exception:  # noqa: BLE001
                quote_volume = None

        return {
            "last": last,
            "change_pct": (last / first - 1.0) * 100.0 if first else 0.0,
            "high": float(recent["high"].max()),
            "low": float(recent["low"].min()),
            "base_volume": float(recent["volume"].sum()),
            "quote_volume": quote_volume,
            "source": self._source,
            "window_hours": round(window * minutes / 60.0, 1),
        }

    def get_order_book(self, symbol, depth=50):
        """Order-book snapshot for microstructure (None when unavailable)."""
        if not self._live or self.exchange is None:
            return None
        try:
            book = self.exchange.fetch_order_book(symbol, limit=int(depth))
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"order book: {exc}"[:200]
            return None

        bids = [b for b in (book.get("bids") or []) if b and len(b) > 1]
        asks = [a for a in (book.get("asks") or []) if a and len(a) > 1]
        if not bids or not asks:
            return None

        bid_size = sum(float(b[1]) for b in bids)
        ask_size = sum(float(a[1]) for a in asks)
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_pct": ((best_ask - best_bid) / mid * 100.0) if mid else None,
            "imbalance": ((bid_size - ask_size) / (bid_size + ask_size)) if (bid_size + ask_size) else 0.0,
            "bid_volume": bid_size,
            "ask_volume": ask_size,
            "levels": min(len(bids), len(asks)),
        }

    # =================================================================
    # helpers
    # =================================================================
    def supported_timeframes(self):
        """Timeframes the active source can actually serve."""
        if self._csv_frame is not None:
            native = self.csv_timeframe
            native_minutes = timeframe_minutes(native)
            pool = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "3h", "4h", "6h", "8h", "12h", "1d", "3d", "1w")
            return [tf for tf in pool if timeframe_minutes(tf) >= native_minutes]
        return ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]


def market_for(symbol=None, source=None):
    """Small factory used by the web layer (fresh instance per request)."""
    return MarketData(source=source)
