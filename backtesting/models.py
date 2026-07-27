from dataclasses import dataclass


@dataclass
class Trade:

    entry_time: object

    exit_time: object

    direction: str

    entry_price: float

    exit_price: float

    stop_loss: float

    take_profit: float

    position_size: float

    leverage: float

    margin_used: float

    entry_fee: float

    exit_fee: float

    funding_fee: float

    slippage_cost: float

    gross_pnl: float

    net_pnl: float

    return_on_margin: float

    exit_reason: str