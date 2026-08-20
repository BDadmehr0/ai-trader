import unittest

from analysis.live import _build_explanation
from analysis.risk import TradeSetup


class BuildExplanationTests(unittest.TestCase):
    def setUp(self):
        self.setup = TradeSetup(
            signal="LONG",
            entry=100.0,
            stop_loss=95.0,
            take_profit_1=107.5,
            take_profit_2=112.5,
            risk_reward_1=1.5,
            risk_reward_2=2.5,
            confidence=80,
            status="LONG SETUP",
        )

    def test_buy_explanation_uses_stop_loss(self):
        explanation = _build_explanation("BUY", self.setup)

        self.assertEqual(
            explanation,
            "Buy (LONG) signal. Entry at 100, Stop Loss 95, Target 108.",
        )

    def test_sell_explanation_uses_stop_loss(self):
        explanation = _build_explanation("SELL", self.setup)

        self.assertEqual(
            explanation,
            "Sell (SHORT) signal. Entry at 100, Stop Loss 95, Target 108.",
        )


if __name__ == "__main__":
    unittest.main()
