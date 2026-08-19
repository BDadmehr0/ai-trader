import logging
import os

import ccxt
import pandas as pd
from dotenv import load_dotenv

from data.demo import ensure_demo_data, load_demo

load_dotenv()

logger = logging.getLogger(__name__)


class MarketData:
    """Fetches OHLCV data from a crypto exchange.

    Uses ccxt + Binance by default. If the exchange cannot be reached
    (no internet, geo-block, VPN needed, ...) it transparently falls back
    to a bundled synthetic dataset so the tool never crashes and is fully
    testable offline.
    """

    def __init__(self, exchange_id="binance"):
        exchange_config = {
            "enableRateLimit": True,
            "timeout": 15000,
        }

        proxy_url = os.getenv("PROXY_URL")

        if proxy_url:
            exchange_config["proxies"] = {
                "http": proxy_url,
                "https": proxy_url,
            }

        self.exchange_id = exchange_id

        self.exchange = getattr(ccxt, exchange_id)(exchange_config)

        self._live = True
        self._last_error = None
        self._fallback_logged = False

    # ===========================================================
    # Data access
    # ===========================================================

    def get_ohlcv(self, symbol, timeframe, limit=1000):
        """Return a clean OHLCV DataFrame (live or demo)."""
        try:
            df = self._fetch_live(symbol, timeframe, limit)
            self._live = True
            return df
        except Exception as exc:  # noqa: BLE001
            self._live = False
            self._last_error = str(exc)
            if not self._fallback_logged:
                self._fallback_logged = True
                logger.warning(
                    "Live data unavailable (%s). Falling back to demo "
                    "data — results are NOT real market prices.",
                    exc,
                )
            return load_demo(timeframe)

    def get_ticker(self, symbol):
        """Return the latest price / 24h change or None when offline."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "last": ticker.get("last"),
                "change_pct": ticker.get("percentage"),
                "high": ticker.get("high"),
                "low": ticker.get("low"),
                "base_volume": ticker.get("baseVolume"),
            }
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            if not self._fallback_logged:
                logger.warning("Ticker fetch failed: %s", exc)
            return None

    @property
    def is_live(self):
        return self._live

    @property
    def last_error(self):
        return self._last_error

    # ===========================================================
    # Internals
    # ===========================================================

    def _fetch_live(self, symbol, timeframe, limit):
        data = self.exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit,
        )

        df = pd.DataFrame(
            data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            unit="ms",
            utc=True,
        )

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        for column in numeric_columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        return df
