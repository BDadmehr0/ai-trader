from data.market_data import MarketData

from analysis.indicators import (
    add_indicators,
)

from analysis.signal import (
    analyze_timeframe,
    generate_signal,
)

from analysis.levels import (
    find_market_levels,
)

from analysis.risk import (
    create_trade_setup,
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
    # Fetch Market Data
    # =========================

    df_15m = market.get_ohlcv(
        symbol=SYMBOL,
        timeframe=TIMEFRAMES["15M"],
    )

    df_1h = market.get_ohlcv(
        symbol=SYMBOL,
        timeframe=TIMEFRAMES["1H"],
    )

    df_4h = market.get_ohlcv(
        symbol=SYMBOL,
        timeframe=TIMEFRAMES["4H"],
    )

    # =========================
    # Indicators
    # =========================

    df_15m = add_indicators(
        df_15m
    )

    df_1h = add_indicators(
        df_1h
    )

    df_4h = add_indicators(
        df_4h
    )

    # =========================
    # Analyze
    # =========================

    analysis_15m = analyze_timeframe(
        df_15m,
        "15M",
    )

    analysis_1h = analyze_timeframe(
        df_1h,
        "1H",
    )

    analysis_4h = analyze_timeframe(
        df_4h,
        "4H",
    )

    # =========================
    # Signal
    # =========================

    signal, confidence = (
        generate_signal(
            analysis_15m,
            analysis_1h,
            analysis_4h,
        )
    )

    # =========================
    # Market Levels
    # =========================

    levels = find_market_levels(
        df_1h
    )

    # =========================
    # Trade Setup
    # =========================

    trade_setup = (
        create_trade_setup(
            signal=signal,
            price=analysis_15m.price,
            atr=analysis_15m.atr,
            support=levels.support_1,
            resistance=levels.resistance_1,
            confidence=confidence,
        )
    )

    # =========================
    # Report
    # =========================

    print_analysis(
        analysis_15m=analysis_15m,
        analysis_1h=analysis_1h,
        analysis_4h=analysis_4h,
        signal=signal,
        confidence=confidence,
        levels=levels,
        trade_setup=trade_setup,
    )


if __name__ == "__main__":

    analyze_btc()