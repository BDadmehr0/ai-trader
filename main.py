from data.market_data import MarketData

from analysis.indicators import (
    add_indicators,
)

from analysis.signal import (
    analyze_timeframe,
    generate_signal,
)

from reports.formatter import (
    print_analysis,
)

from config.settings import (
    SYMBOL,
    TIMEFRAMES,
)


def analyze_btc():

    print(
        "Fetching BTC market data..."
    )

    market = MarketData()

    # =========================
    # Fetch 1H
    # =========================

    df_1h = market.get_ohlcv(
        symbol=SYMBOL,
        timeframe=TIMEFRAMES["1H"],
    )

    # =========================
    # Fetch 4H
    # =========================

    df_4h = market.get_ohlcv(
        symbol=SYMBOL,
        timeframe=TIMEFRAMES["4H"],
    )

    # =========================
    # Calculate Indicators
    # =========================

    df_1h = add_indicators(
        df_1h
    )

    df_4h = add_indicators(
        df_4h
    )

    # =========================
    # Analyze Timeframes
    # =========================

    analysis_1h = analyze_timeframe(
        df=df_1h,
        timeframe="1H",
    )

    analysis_4h = analyze_timeframe(
        df=df_4h,
        timeframe="4H",
    )

    # =========================
    # Generate Signal
    # =========================

    signal = generate_signal(
        analysis_1h=analysis_1h,
        analysis_4h=analysis_4h,
    )

    # =========================
    # Print Report
    # =========================

    print_analysis(
        analysis_1h=analysis_1h,
        analysis_4h=analysis_4h,
        signal=signal,
    )


if __name__ == "__main__":
    analyze_btc()