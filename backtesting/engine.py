import math
import threading

from analysis.strategy import (
    generate_signal,
)

from backtesting.models import (
    Trade,
)

from config.store import get_settings

# Names the engine body uses (kept as module globals so the algorithm below
# stays readable). They are refreshed from the live settings store at the start
# of every run(), which is what lets the /settings page and the optimizer change
# risk parameters without restarting anything.
_SETTINGS_KEYS = {
    "RISK_PER_TRADE": "risk_per_trade",
    "ATR_STOP_MULTIPLIER": "atr_stop_multiplier",
    "ATR_TP_MULTIPLIER": "atr_tp_multiplier",
    "LEVERAGE": "leverage",
    "TAKER_FEE": "taker_fee",
    "SLIPPAGE": "slippage",
    "FUNDING_RATE": "funding_rate",
    "FUNDING_INTERVAL_HOURS": "funding_interval_hours",
    "MAINTENANCE_MARGIN": "maintenance_margin",
    "MAX_HOLDING_CANDLES": "max_holding_candles",
    "COOLDOWN_CANDLES": "cooldown_candles",
    "ENABLE_BREAK_EVEN": "enable_break_even",
    "BREAK_EVEN_R": "break_even_r",
    "BREAK_EVEN_OFFSET": "break_even_offset",
    "ENABLE_TRAILING_STOP": "enable_trailing_stop",
    "TRAILING_ATR_MULTIPLIER": "trailing_atr_multiplier",
    "MIN_VOLUME_RATIO": "min_volume_ratio",
    "PULLBACK_DISTANCE": "pullback_distance",
}

#: the module globals above are shared, so runs are serialised
_RUN_LOCK = threading.Lock()


def _apply_settings(settings):
    globals().update({name: settings.get(key) for name, key in _SETTINGS_KEYS.items()})


class BacktestEngine:

    def __init__(
        self,
        initial_balance=None,
        settings=None,
    ):

        self.settings = settings or get_settings()

        initial_balance = (
            initial_balance
            if initial_balance is not None
            else float(self.settings.get("initial_balance", 10000.0))
        )

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
        """Run the simulation with the effective settings applied."""
        settings = self.settings or get_settings()
        with _RUN_LOCK:
            _apply_settings(settings)
            return self._run_impl(df)

    def _run_impl(
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
                self.settings or get_settings(),
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

        stop_distance, tp_distance = self._distances(
            row,
            direction,
            atr,
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

        leverage = max(1.0, float(LEVERAGE))

        max_notional = (

            self.balance

            * leverage

        )

        if notional > max_notional > 0:

            position_size = max_notional / entry_price

            notional = max_notional

        margin_used = (

            notional

            / leverage

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
    # Stop / Target geometry
    # =================================

    def _distances(
        self,
        row,
        direction,
        atr,
    ):
        """Stop and target distances honouring stop_mode / target_mode."""

        settings = self.settings or get_settings()

        stop_distance = max(
            1e-12,
            atr * float(settings.get("atr_stop_multiplier", ATR_STOP_MULTIPLIER)),
        )

        ref = float(row["close"])
        mode = str(settings.get("stop_mode", "atr"))

        if mode in ("structure", "hybrid"):

            key = "dc_lower" if direction == "LONG" else "dc_upper"
            level = _read(row, key)

            if level:

                buffer = float(settings.get("stop_structure_buffer", 0.25)) * atr

                structure = (ref - level + buffer) if direction == "LONG" else (level - ref + buffer)

                cap = 3.0 * atr if atr > 0 else ref * 0.06

                if 0 < structure <= cap:

                    stop_distance = (
                        structure
                        if mode == "structure"
                        else max(stop_distance, structure)
                    )

        target_mode = str(settings.get("target_mode", "atr"))
        tp_distance = atr * float(settings.get("atr_tp_multiplier", ATR_TP_MULTIPLIER))

        if target_mode == "rr":

            tp_distance = stop_distance * float(settings.get("tp2_r", 2.5))

        elif target_mode == "structure":

            key = "dc_upper" if direction == "LONG" else "dc_lower"
            level = _read(row, key)

            if level:

                distance = (level - ref) if direction == "LONG" else (ref - level)

                if distance >= stop_distance:

                    tp_distance = distance

        return stop_distance, tp_distance

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


def _read(row, key):
    """Read an optional indicator column from a pandas row (NaN-safe)."""
    try:
        value = float(row[key])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    return value
