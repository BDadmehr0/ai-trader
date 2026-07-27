import os

import ccxt
import pandas as pd
from dotenv import load_dotenv

from config.settings import CANDLE_LIMIT


load_dotenv()


class MarketData:

    def __init__(self):
        exchange_config = {
            "enableRateLimit": True,
        }

        proxy_url = os.getenv("PROXY_URL")

        if proxy_url:
            exchange_config["proxies"] = {
                "http": proxy_url,
                "https": proxy_url,
            }

        self.exchange = ccxt.binance(exchange_config)

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
    ) -> pd.DataFrame:

        candles = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=CANDLE_LIMIT,
        )

        if not candles:
            raise RuntimeError(
                f"No market data received for {symbol} {timeframe}"
            )

        df = pd.DataFrame(
            candles,
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
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

        return df.dropna()