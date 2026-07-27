from dataclasses import dataclass


@dataclass
class TradeSetup:

    signal: str

    entry: float

    stop_loss: float

    take_profit_1: float

    take_profit_2: float

    risk_reward_1: float

    risk_reward_2: float

    confidence: int

    status: str


def create_trade_setup(
    signal,
    price,
    atr,
    support,
    resistance,
    confidence,
):

    # =========================
    # LONG
    # =========================

    if signal == "LONG":

        entry = price

        stop_loss = (
            entry
            - atr * 1.5
        )

        risk = (
            entry
            - stop_loss
        )

        take_profit_1 = (
            entry
            + risk * 1.5
        )

        take_profit_2 = (
            entry
            + risk * 2.5
        )

        rr1 = (
            take_profit_1
            - entry
        ) / risk

        rr2 = (
            take_profit_2
            - entry
        ) / risk

        if (
            resistance > entry
            and resistance < take_profit_1
        ):

            status = (
                "WAIT - RESISTANCE NEARBY"
            )

        else:

            status = (
                "LONG SETUP"
            )

    # =========================
    # SHORT
    # =========================

    elif signal == "SHORT":

        entry = price

        stop_loss = (
            entry
            + atr * 1.5
        )

        risk = (
            stop_loss
            - entry
        )

        take_profit_1 = (
            entry
            - risk * 1.5
        )

        take_profit_2 = (
            entry
            - risk * 2.5
        )

        rr1 = (
            entry
            - take_profit_1
        ) / risk

        rr2 = (
            entry
            - take_profit_2
        ) / risk

        if (
            support < entry
            and support > take_profit_1
        ):

            status = (
                "WAIT - SUPPORT NEARBY"
            )

        else:

            status = (
                "SHORT SETUP"
            )

    # =========================
    # WAIT
    # =========================

    else:

        return TradeSetup(
            signal="WAIT",
            entry=price,
            stop_loss=0,
            take_profit_1=0,
            take_profit_2=0,
            risk_reward_1=0,
            risk_reward_2=0,
            confidence=confidence,
            status="NO TRADE",
        )

    return TradeSetup(
        signal=signal,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_reward_1=rr1,
        risk_reward_2=rr2,
        confidence=confidence,
        status=status,
    )