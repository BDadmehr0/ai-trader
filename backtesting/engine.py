import math

from backtesting.models import Trade

from backtesting.strategy import (
    generate_mtf_signal,
)

from config.settings import (
    RISK_PER_TRADE,
    ATR_STOP_MULTIPLIER,
    TAKE_PROFIT_RR,
    MAX_HOLDING_CANDLES,
    LEVERAGE,
    TAKER_FEE,
    SLIPPAGE,
    FUNDING_RATE,
    FUNDING_INTERVAL_HOURS,
    MAINTENANCE_MARGIN,
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

            row = df.iloc[i]

            previous = (
                df.iloc[i - 1]
            )

            # -------------------------
            # Manage Existing Position
            # -------------------------

            if position:

                holding_candles += 1

                position["holding_candles"] = (
                    holding_candles
                )

                exit_result = (
                    self.check_exit(
                        position,
                        row,
                        holding_candles,
                    )
                )

                if exit_result:

                    trade = (
                        self.close_position(
                            position,
                            row,
                            exit_result,
                        )
                    )

                    self.trades.append(
                        trade
                    )

                    position = None

                    holding_candles = 0

                else:

                    self.equity_curve.append(
                        self.mark_to_market(
                            position,
                            row,
                        )
                    )

                continue

            # -------------------------
            # Signal
            # -------------------------

            signal = (
                generate_mtf_signal(
                    row_4h={
                        "close": row[
                            "close_4h"
                        ],
                        "ema20": row[
                            "ema20_4h"
                        ],
                        "ema50": row[
                            "ema50_4h"
                        ],
                        "ema200": row[
                            "ema200_4h"
                        ],
                        "macd": row[
                            "macd_4h"
                        ],
                        "macd_signal": row[
                            "macd_signal_4h"
                        ],
                        "rsi": row[
                            "rsi_4h"
                        ],
                    },

                    row_1h={
                        "close": row[
                            "close_1h"
                        ],
                        "ema20": row[
                            "ema20_1h"
                        ],
                        "ema50": row[
                            "ema50_1h"
                        ],
                        "ema200": row[
                            "ema200_1h"
                        ],
                        "macd": row[
                            "macd_1h"
                        ],
                        "macd_signal": row[
                            "macd_signal_1h"
                        ],
                        "rsi": row[
                            "rsi_1h"
                        ],
                        "atr": row[
                            "atr_1h"
                        ],
                    },

                    row_15m={
                        "close": row[
                            "close"
                        ],
                        "ema20": row[
                            "ema20"
                        ],
                        "ema50": row[
                            "ema50"
                        ],
                        "ema200": row[
                            "ema200"
                        ],
                        "macd": row[
                            "macd"
                        ],
                        "macd_signal": row[
                            "macd_signal"
                        ],
                        "rsi": row[
                            "rsi"
                        ],
                    },
                )
            )

            if (
                signal.direction
                == "WAIT"
            ):

                self.equity_curve.append(
                    self.balance
                )

                continue

            # -------------------------
            # Open
            # -------------------------

            position = (
                self.open_position(
                    row,
                    signal.direction,
                )
            )

            self.equity_curve.append(
                self.balance
            )

        return self.trades

    def open_position(
        self,
        row,
        direction,
    ):

        raw_entry = float(
            row["close"]
        )

        # Slippage

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

        atr = float(
            row["atr"]
        )

        stop_distance = (
            atr
            * ATR_STOP_MULTIPLIER
        )

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

        margin_used = (
            notional
            / LEVERAGE
        )

        entry_fee = (
            notional
            * TAKER_FEE
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

        self.balance -= entry_fee

        return {
            "entry_time": row[
                "timestamp"
            ],

            "direction": direction,

            "entry_price": entry_price,

            "stop_loss": stop_loss,

            "take_profit": take_profit,

            "position_size": position_size,

            "margin_used": margin_used,

            "entry_fee": entry_fee,

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

        direction = (
            position["direction"]
        )

        if direction == "LONG":

            if (
                low
                <= position[
                    "stop_loss"
                ]
            ):

                return {
                    "price": position[
                        "stop_loss"
                    ],
                    "reason": "STOP_LOSS",
                }

            if (
                high
                >= position[
                    "take_profit"
                ]
            ):

                return {
                    "price": position[
                        "take_profit"
                    ],
                    "reason": "TAKE_PROFIT",
                }

        else:

            if (
                high
                >= position[
                    "stop_loss"
                ]
            ):

                return {
                    "price": position[
                        "stop_loss"
                    ],
                    "reason": "STOP_LOSS",
                }

            if (
                low
                <= position[
                    "take_profit"
                ]
            ):

                return {
                    "price": position[
                        "take_profit"
                    ],
                    "reason": "TAKE_PROFIT",
                }

        if (
            holding_candles
            >= MAX_HOLDING_CANDLES
        ):

            return {
                "price": float(
                    row["close"]
                ),
                "reason": "TIME_EXIT",
            }

        return None

    def close_position(
        self,
        position,
        row,
        result,
    ):

        raw_exit = float(
            result["price"]
        )

        direction = (
            position["direction"]
        )

        if direction == "LONG":

            exit_price = (
                raw_exit
                * (1 - SLIPPAGE)
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
                * (1 + SLIPPAGE)
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

        funding_intervals = (
            math.floor(
                holding_hours
                / FUNDING_INTERVAL_HOURS
            )
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
            entry_time=position[
                "entry_time"
            ],

            exit_time=row[
                "timestamp"
            ],

            direction=direction,

            entry_price=position[
                "entry_price"
            ],

            exit_price=exit_price,

            stop_loss=position[
                "stop_loss"
            ],

            take_profit=position[
                "take_profit"
            ],

            position_size=position[
                "position_size"
            ],

            leverage=LEVERAGE,

            margin_used=position[
                "margin_used"
            ],

            entry_fee=position[
                "entry_fee"
            ],

            exit_fee=exit_fee,

            funding_fee=funding_fee,

            slippage_cost=slippage_cost,

            gross_pnl=gross_pnl,

            net_pnl=net_pnl,

            return_on_margin=(
                net_pnl
                / position[
                    "margin_used"
                ]
                * 100
            ),

            exit_reason=result[
                "reason"
            ],
        )

    def mark_to_market(
        self,
        position,
        row,
    ):

        price = float(
            row["close"]
        )

        if (
            position["direction"]
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