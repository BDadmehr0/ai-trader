"""Equity-curve chart for the backtest report (matplotlib, optional)."""

import matplotlib

matplotlib.use("Agg", force=False)

import matplotlib.pyplot as plt  # noqa: E402


def _values(equity_curve):
    """Accept floats, {"equity": x} rows or (time, value) tuples."""
    values = []
    for point in equity_curve or []:
        if isinstance(point, dict):
            point = point.get("equity")
        elif isinstance(point, (list, tuple)):
            point = point[-1]
        if point is not None:
            values.append(float(point))
    return values


def plot_equity_curve(equity_curve, filename="equity_curve.png", title=None, show=None):
    values = _values(equity_curve)
    if len(values) < 2:
        return None

    plt.figure(figsize=(12, 6))
    plt.plot(values, color="#1e80ff", linewidth=1.6)
    plt.fill_between(range(len(values)), min(values), values, color="#1e80ff", alpha=0.12)
    plt.title(title or "AI TRADER - Equity Curve")
    plt.xlabel("Backtest Step")
    plt.ylabel("Equity")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(filename, dpi=110, facecolor="#0b0e11")

    interactive = show if show is not None else "agg" not in matplotlib.get_backend().lower()
    if interactive:  # pragma: no cover - only when a display is available
        plt.show()
    plt.close()

    return filename
