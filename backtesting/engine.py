import pandas as pd

from backtesting.models import Trade

from backtesting.strategy import (
    calculate_signal,
)

from config.settings import (
    INITIAL_BALANCE,
    RISK_PER_TRADE,
    TAKE_PROFIT_RR,
    ATR_STOP_MULTIPLIER,
    MAX_HOLDING_CANDLES,
)


class BacktestEngine:

    def __init__(
        self,
        initial_balance=INITIAL_BALANCE,
    ):

        self.initial_balance = (
            initial_balance
        )

        self.balance = (
            initial_balance
        )

        self.equity_curve = []

        self.trades = []

    def run(
        self,
        df: pd.DataFrame,
    ):

        df = df.reset_index(
            drop=True
        )

        position = None

        holding_candles = 0

        for i in range(
            1,
            len(df),
        ):

            row = df.iloc[i]

            previous_row = (
                df.iloc[i - 1]
            )

            # =========================
            # Existing Position
            # =========================

            if position is not None:

                holding_candles += 1

                result = (
                    self.check_exit(
                        position,
                        row,
                        holding_candles,
                    )
                )

                if result is not None:

                    trade = (
                        self.close_position(
                            position,
                            result,
                        )
                    )

                    self.trades.append(
                        trade
                    )

                    position = None

                    holding_candles = 0

                    self.equity_curve.append(
                        self.balance
                    )

                    continue

                self.equity_curve.append(
                    self.calculate_equity(
                        position,
                        row,
                    )
                )

                continue

            # =========================
            # New Signal
            # =========================

            signal = calculate_signal(
                previous_row
            )

            if signal.direction == "WAIT":

                self.equity_curve.append(
                    self.balance
                )

                continue

            # =========================
            # Open Position
            # =========================

            position = (
                self.open_position(
                    row,
                    signal.direction,
                )
            )

            self.equity_curve.append(
                self.balance
            )

        # =========================
        # Close Open Position
        # =========================

        if position is not None:

            last_row = df.iloc[-1]

            trade = (
                self.close_position(
                    position,
                    {
                        "price": float(
                            last_row["close"]
                        ),
                        "reason": "END_OF_DATA",
                    },
                )
            )

            self.trades.append(
                trade
            )

        return self.trades

    def open_position(
        self,
        row,
        direction,
    ):

        entry_price = float(
            row["open"]
        )

        atr = float(
            row["atr"]
        )

        risk_per_trade = (
            self.balance
            * RISK_PER_TRADE
        )

        stop_distance = (
            atr
            * ATR_STOP_MULTIPLIER
        )

        if stop_distance <= 0:

            stop_distance = (
                entry_price
                * 0.01
            )

        position_size = (
            risk_per_trade
            / stop_distance
        )

        if direction == "LONG":

            stop_loss = (
                entry_price
                - stop_distance
            )

            take_profit = (
                entry_price
                + stop_distance
                * TAKE_PROFIT_RR
            )

        else:

            stop_loss = (
                entry_price
                + stop_distance
            )

            take_profit = (
                entry_price
                - stop_distance
                * TAKE_PROFIT_RR
            )

        return {
            "entry_time": row["timestamp"],
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_size": position_size,
            "holding_candles": 0,
        }

    def check_exit(
        self,
        position,
        row,
        holding_candles,
    ):

        high = float(
            row["high"]
        )

        low = float(
            row["low"]
        )

        if (
            position["direction"]
            == "LONG"
        ):

            stop_hit = (
                low
                <= position[
                    "stop_loss"
                ]
            )

            target_hit = (
                high
                >= position[
                    "take_profit"
                ]
            )

            if stop_hit and target_hit:

                return {
                    "price": position[
                        "stop_loss"
                    ],
                    "reason": (
                        "STOP_LOSS"
                    ),
                }

            if stop_hit:

                return {
                    "price": position[
                        "stop_loss"
                    ],
                    "reason": (
                        "STOP_LOSS"
                    ),
                }

            if target_hit:

                return {
                    "price": position[
                        "take_profit"
                    ],
                    "reason": (
                        "TAKE_PROFIT"
                    ),
                }

        else:

            stop_hit = (
                high
                >= position[
                    "stop_loss"
                ]
            )

            target_hit = (
                low
                <= position[
                    "take_profit"
                ]
            )

            if stop_hit and target_hit:

                return {
                    "price": position[
                        "stop_loss"
                    ],
                    "reason": (
                        "STOP_LOSS"
                    ),
                }

            if stop_hit:

                return {
                    "price": position[
                        "stop_loss"
                    ],
                    "reason": (
                        "STOP_LOSS"
                    ),
                }

            if target_hit:

                return {
                    "price": position[
                        "take_profit"
                    ],
                    "reason": (
                        "TAKE_PROFIT"
                    ),
                }

        if (
            holding_candles
            >= MAX_HOLDING_CANDLES
        ):

            return {
                "price": float(
                    row["close"]
                ),
                "reason": (
                    "TIME_EXIT"
                ),
            }

        return None

    def close_position(
        self,
        position,
        result,
    ):

        entry = (
            position[
                "entry_price"
            ]
        )

        exit_price = (
            result["price"]
        )

        size = (
            position[
                "position_size"
            ]
        )

        if (
            position["direction"]
            == "LONG"
        ):

            pnl = (
                exit_price
                - entry
            ) * size

        else:

            pnl = (
                entry
                - exit_price
            ) * size

        pnl_percent = (
            pnl
            / self.balance
            * 100
        )

        self.balance += pnl

        return Trade(
            entry_time=position[
                "entry_time"
            ],

            exit_time=None,

            direction=position[
                "direction"
            ],

            entry_price=entry,

            exit_price=exit_price,

            stop_loss=position[
                "stop_loss"
            ],

            take_profit=position[
                "take_profit"
            ],

            position_size=size,

            pnl=pnl,

            pnl_percent=pnl_percent,

            exit_reason=result[
                "reason"
            ],
        )

    def calculate_equity(
        self,
        position,
        row,
    ):

        current_price = float(
            row["close"]
        )

        entry = (
            position[
                "entry_price"
            ]
        )

        size = (
            position[
                "position_size"
            ]
        )

        if (
            position["direction"]
            == "LONG"
        ):

            unrealized = (
                current_price
                - entry
            ) * size

        else:

            unrealized = (
                entry
                - current_price
            ) * size

        return (
            self.balance
            + unrealized
        )