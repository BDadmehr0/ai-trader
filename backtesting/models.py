from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:

    entry_time: datetime

    exit_time: datetime

    direction: str

    entry_price: float

    exit_price: float

    stop_loss: float

    take_profit: float

    position_size: float

    pnl: float

    pnl_percent: float

    exit_reason: str