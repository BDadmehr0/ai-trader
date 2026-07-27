import math

from analysis.strategy import (
    generate_signal,
)

from backtesting.models import (
    Trade,
)

from config.settings import (
    RISK_PER_TRADE,
    ATR_STOP_MULTIPLIER,
    ATR_TP_MULTIPLIER,
    LEVERAGE,
    TAKER_FEE,
    SLIPPAGE,
    FUNDING_RATE,
    FUNDING_INTERVAL_HOURS,
    MAINTENANCE_MARGIN,
    MAX_HOLDING_CANDLES,
    COOLDOWN_CANDLES,
    ENABLE_BREAK_EVEN,
    BREAK_EVEN_R,
    BREAK_EVEN_OFFSET,
    ENABLE_TRAILING_STOP,
    TRAILING_ATR_MULTIPLIER,
)


class BacktestEngine:

    def __init__(
        self,
        initial_balance,
    ):

        self.initial_balance = (
            initial_balance
        )

        self.balance = (
            initial_balance
        )

        self.equity_curve = []

        self.trades = []

        self.cooldown = 0

    # =================================
    # Main Backtest
    # =================================

    def run(
        self,
        df,
    ):

        position = None

        holding_candles = 0

        for i in range(
            1,
            len(df),
        ):

            previous = df.iloc[
                i - 1
            ]

            current = df.iloc[
                i
            ]

            # =========================
            # Existing Position
            # =========================

            if position is not None:

                holding_candles += 1

                position[
                    "holding_candles"
                ] = holding_candles

                # ---------------------
                # Update Stop
                # ---------------------

                self.update_stop(
                    position,
                    current,
                )

                # ---------------------
                # Check Liquidation
                # ---------------------

                liquidation_price = (
                    self.get_liquidation_price(
                        position
                    )
                )

                if self.check_liquidation(
                    position,
                    current,
                    liquidation_price,
                ):

                    trade = (
                        self.close_position(
                            position,
                            current,
                            liquidation_price,
                            "LIQUIDATION",
                        )
                    )

                    self.trades.append(
                        trade
                    )

                    position = None

                    holding_candles = 0

                    self.cooldown = (
                        COOLDOWN_CANDLES
                    )

                    continue

                # ---------------------
                # Check SL / TP
                # ---------------------

                exit_result = (
                    self.check_exit(
                        position,
                        current,
                    )
                )

                if exit_result:

                    trade = (
                        self.close_position(
                            position,
                            current,
                            exit_result[
                                "price"
                            ],
                            exit_result[
                                "reason"
                            ],
                        )
                    )

                    self.trades.append(
                        trade
                    )

                    position = None

                    holding_candles = 0

                    self.cooldown = (
                        COOLDOWN_CANDLES
                    )

                    continue

                # ---------------------
                # Time Exit
                # ---------------------

                if (
                    holding_candles
                    >= MAX_HOLDING_CANDLES
                ):

                    trade = (
                        self.close_position(
                            position,
                            current,
                            float(
                                current[
                                    "close"
                                ]
                            ),
                            "TIME_EXIT",
                        )
                    )

                    self.trades.append(
                        trade
                    )

                    position = None

                    holding_candles = 0

                    self.cooldown = (
                        COOLDOWN_CANDLES
                    )

                    continue

                self.equity_curve.append(
                    self.mark_to_market(
                        position,
                        current,
                    )
                )

                continue

            # =========================
            # Cooldown
            # =========================

            if self.cooldown > 0:

                self.cooldown -= 1

                self.equity_curve.append(
                    self.balance
                )

                continue

            # =========================
            # Generate Signal
            # =========================

            signal = generate_signal(
                previous,
                current,
            )

            if signal == "WAIT":

                self.equity_curve.append(
                    self.balance
                )

                continue

            # =========================
            # Open Position
            # =========================

            position = (
                self.open_position(
                    current,
                    signal,
                )
            )

            holding_candles = 0

            self.equity_curve.append(
                self.balance
            )

        return self.trades

    # =================================
    # Open Position
    # =================================

    def open_position(
        self,
        row,
        direction,
    ):

        raw_entry = float(
            row["close"]
        )

        atr = float(
            row["atr"]
        )

        stop_distance = (

            atr

            * ATR_STOP_MULTIPLIER

        )

        tp_distance = (

            atr

            * ATR_TP_MULTIPLIER

        )

        # -------------------------
        # Slippage
        # -------------------------

        if direction == "LONG":

            entry_price = (

                raw_entry

                * (1 + SLIPPAGE)

            )

        else:

            entry_price = (

                raw_entry

                * (1 - SLIPPAGE)

            )

        # -------------------------
        # Stop
        # -------------------------

        if direction == "LONG":

            stop_loss = (

                entry_price

                - stop_distance

            )

            take_profit = (

                entry_price

                + tp_distance

            )

        else:

            stop_loss = (

                entry_price

                + stop_distance

            )

            take_profit = (

                entry_price

                - tp_distance

            )

        # -------------------------
        # Risk Position Sizing
        # -------------------------

        risk_amount = (

            self.balance

            * RISK_PER_TRADE

        )

        position_size = (

            risk_amount

            / stop_distance

        )

        notional = (

            position_size

            * entry_price

        )

        # -------------------------
        # Leverage
        # -------------------------

        margin_used = (

            notional

            / LEVERAGE

        )

        # -------------------------
        # Fee
        # -------------------------

        entry_fee = (

            notional

            * TAKER_FEE

        )

        self.balance -= (
            entry_fee
        )

        return {

            "entry_time":
                row["timestamp"],

            "direction":
                direction,

            "entry_price":
                entry_price,

            "initial_stop":
                stop_loss,

            "stop_loss":
                stop_loss,

            "take_profit":
                take_profit,

            "position_size":
                position_size,

            "margin_used":
                margin_used,

            "entry_fee":
                entry_fee,

            "holding_candles":
                0,

            "break_even_active":
                False,

        }

    # =================================
    # Dynamic Stop
    # =================================

    def update_stop(
        self,
        position,
        row,
    ):

        atr = float(
            row["atr"]
        )

        entry = (
            position[
                "entry_price"
            ]
        )

        current = float(
            row["close"]
        )

        initial_stop = (
            position[
                "initial_stop"
            ]
        )

        # =========================
        # LONG
        # =========================

        if (
            position[
                "direction"
            ]
            == "LONG"
        ):

            risk = (

                entry

                - initial_stop

            )

            profit = (

                current

                - entry

            )

            # ---------------------
            # Break Even
            # ---------------------

            if (

                ENABLE_BREAK_EVEN

                and

                profit
                >= risk
                * BREAK_EVEN_R

            ):

                break_even_stop = (

                    entry

                    * (
                        1
                        + BREAK_EVEN_OFFSET
                    )

                )

                position[
                    "stop_loss"
                ] = max(

                    position[
                        "stop_loss"
                    ],

                    break_even_stop,

                )

            # ---------------------
            # Trailing
            # ---------------------

            if (
                ENABLE_TRAILING_STOP
            ):

                trailing_stop = (

                    current

                    - (

                        atr

                        * TRAILING_ATR_MULTIPLIER

                    )

                )

                position[
                    "stop_loss"
                ] = max(

                    position[
                        "stop_loss"
                    ],

                    trailing_stop,

                )

        # =========================
        # SHORT
        # =========================

        else:

            risk = (

                initial_stop

                - entry

            )

            profit = (

                entry

                - current

            )

            # ---------------------
            # Break Even
            # ---------------------

            if (

                ENABLE_BREAK_EVEN

                and

                profit
                >= risk
                * BREAK_EVEN_R

            ):

                break_even_stop = (

                    entry

                    * (
                        1
                        - BREAK_EVEN_OFFSET
                    )

                )

                position[
                    "stop_loss"
                ] = min(

                    position[
                        "stop_loss"
                    ],

                    break_even_stop,

                )

            # ---------------------
            # Trailing
            # ---------------------

            if (
                ENABLE_TRAILING_STOP
            ):

                trailing_stop = (

                    current

                    + (

                        atr

                        * TRAILING_ATR_MULTIPLIER

                    )

                )

                position[
                    "stop_loss"
                ] = min(

                    position[
                        "stop_loss"
                    ],

                    trailing_stop,

                )

    # =================================
    # Exit
    # =================================

    def check_exit(
        self,
        position,
        row,
    ):

        high = float(
            row["high"]
        )

        low = float(
            row["low"]
        )

        direction = (
            position[
                "direction"
            ]
        )

        stop = (
            position[
                "stop_loss"
            ]
        )

        target = (
            position[
                "take_profit"
            ]
        )

        if direction == "LONG":

            # Stop

            if low <= stop:

                return {

                    "price":
                        stop,

                    "reason":
                        "STOP_LOSS",

                }

            # TP

            if high >= target:

                return {

                    "price":
                        target,

                    "reason":
                        "TAKE_PROFIT",

                }

        else:

            # Stop

            if high >= stop:

                return {

                    "price":
                        stop,

                    "reason":
                        "STOP_LOSS",

                }

            # TP

            if low <= target:

                return {

                    "price":
                        target,

                    "reason":
                        "TAKE_PROFIT",

                }

        return None

    # =================================
    # Liquidation
    # =================================

    def get_liquidation_price(
        self,
        position,
    ):

        entry = (
            position[
                "entry_price"
            ]
        )

        if (
            position[
                "direction"
            ]
            == "LONG"
        ):

            return (

                entry

                * (

                    1

                    - (

                        1
                        / LEVERAGE
                    )

                    + MAINTENANCE_MARGIN

                )

            )

        return (

            entry

            * (

                1

                + (

                    1
                    / LEVERAGE
                )

                - MAINTENANCE_MARGIN

            )

        )

    def check_liquidation(
        self,
        position,
        row,
        liquidation_price,
    ):

        if (
            position[
                "direction"
            ]
            == "LONG"
        ):

            return (

                float(
                    row["low"]
                )

                <= liquidation_price

            )

        return (

            float(
                row["high"]
            )

            >= liquidation_price

        )

    # =================================
    # Close Position
    # =================================

    def close_position(
        self,
        position,
        row,
        raw_exit,
        reason,
    ):

        direction = (
            position[
                "direction"
            ]
        )

        if direction == "LONG":

            exit_price = (

                raw_exit

                * (

                    1
                    - SLIPPAGE

                )

            )

            gross_pnl = (

                exit_price

                - position[
                    "entry_price"
                ]

            ) * position[
                "position_size"
            ]

        else:

            exit_price = (

                raw_exit

                * (

                    1
                    + SLIPPAGE

                )

            )

            gross_pnl = (

                position[
                    "entry_price"
                ]

                - exit_price

            ) * position[
                "position_size"
            ]

        notional = (

            exit_price

            * position[
                "position_size"
            ]

        )

        exit_fee = (

            notional

            * TAKER_FEE

        )

        holding_hours = (

            position[
                "holding_candles"
            ]

            * 0.25

        )

        funding_intervals = math.floor(

            holding_hours

            / FUNDING_INTERVAL_HOURS

        )

        funding_fee = (

            notional

            * FUNDING_RATE

            * funding_intervals

        )

        slippage_cost = (

            abs(

                raw_exit

                - exit_price

            )

            * position[
                "position_size"
            ]

        )

        net_pnl = (

            gross_pnl

            - position[
                "entry_fee"
            ]

            - exit_fee

            - funding_fee

        )

        self.balance += (
            net_pnl
        )

        return Trade(

            entry_time=
                position[
                    "entry_time"
                ],

            exit_time=
                row[
                    "timestamp"
                ],

            direction=
                direction,

            entry_price=
                position[
                    "entry_price"
                ],

            exit_price=
                exit_price,

            initial_stop=
                position[
                    "initial_stop"
                ],

            final_stop=
                position[
                    "stop_loss"
                ],

            take_profit=
                position[
                    "take_profit"
                ],

            position_size=
                position[
                    "position_size"
                ],

            leverage=
                LEVERAGE,

            margin_used=
                position[
                    "margin_used"
                ],

            entry_fee=
                position[
                    "entry_fee"
                ],

            exit_fee=
                exit_fee,

            funding_fee=
                funding_fee,

            slippage_cost=
                slippage_cost,

            gross_pnl=
                gross_pnl,

            net_pnl=
                net_pnl,

            return_on_margin=(

                net_pnl

                / position[
                    "margin_used"
                ]

                * 100

            ),

            exit_reason=
                reason,

            holding_candles=
                position[
                    "holding_candles"
                ],

        )

    # =================================
    # Mark To Market
    # =================================

    def mark_to_market(
        self,
        position,
        row,
    ):

        price = float(
            row["close"]
        )

        if (
            position[
                "direction"
            ]
            == "LONG"
        ):

            unrealized = (

                price

                - position[
                    "entry_price"
                ]

            ) * position[
                "position_size"
            ]

        else:

            unrealized = (

                position[
                    "entry_price"
                ]

                - price

            ) * position[
                "position_size"
            ]

        return (

            self.balance

            + unrealized

        )