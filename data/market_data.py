import os

import ccxt
import pandas as pd
from dotenv import load_dotenv


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

        self.exchange = ccxt.binance(
            exchange_config
        )

    def get_ohlcv(
        self,
        symbol,
        timeframe,
        limit=1000,
    ):

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

            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

        return df