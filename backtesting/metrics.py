# ============================================================
#  backtesting/metrics.py — Performance statistics
# ============================================================
#
#  Trade list (SimTrade with r_multiple set) se institutional
#  performance metrics nikalta hai. R-multiple based rakha hai
#  taake account size se independent ho (position sizing alag
#  layer hai). Dollar P&L bhi optional deta hai agar risk_$ pata ho.
# ============================================================

from dataclasses import dataclass


@dataclass
class BacktestStats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    total_r: float = 0.0
    avg_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    expectancy_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    max_consecutive_losses: int = 0
    best_r: float = 0.0
    worst_r: float = 0.0

    def summary(self) -> str:
        return (
            f"Trades: {self.trades} | WR: {self.win_rate*100:.1f}% "
            f"({self.wins}W/{self.losses}L/{self.breakeven}BE)\n"
            f"Total: {self.total_r:+.2f}R | Expectancy: {self.expectancy_r:+.3f}R/trade\n"
            f"Avg win: {self.avg_win_r:+.2f}R | Avg loss: {self.avg_loss_r:+.2f}R | "
            f"Profit factor: {self.profit_factor:.2f}\n"
            f"Max drawdown: {self.max_drawdown_r:.2f}R | "
            f"Max consecutive losses: {self.max_consecutive_losses}\n"
            f"Best: {self.best_r:+.2f}R | Worst: {self.worst_r:+.2f}R"
        )


def compute(trades: list) -> BacktestStats:
    """trades: list of SimTrade (or objects with .r_multiple)."""
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    s = BacktestStats(trades=len(rs))
    if not rs:
        return s

    wins   = [r for r in rs if r > 1e-9]
    losses = [r for r in rs if r < -1e-9]
    be     = [r for r in rs if abs(r) <= 1e-9]

    s.wins = len(wins)
    s.losses = len(losses)
    s.breakeven = len(be)
    s.win_rate = s.wins / s.trades if s.trades else 0.0
    s.total_r = sum(rs)
    s.avg_r = s.total_r / s.trades
    s.avg_win_r = sum(wins) / len(wins) if wins else 0.0
    s.avg_loss_r = sum(losses) / len(losses) if losses else 0.0
    s.best_r = max(rs)
    s.worst_r = min(rs)

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    s.profit_factor = (gross_win / gross_loss) if gross_loss > 1e-9 else float("inf")

    # Expectancy = WR*avgWin - LR*avgLoss (avgLoss negative)
    lr = s.losses / s.trades if s.trades else 0.0
    s.expectancy_r = s.win_rate * s.avg_win_r + lr * s.avg_loss_r

    # Equity curve drawdown (in R)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    s.max_drawdown_r = max_dd

    # Max consecutive losses
    run = 0
    worst_run = 0
    for r in rs:
        if r < -1e-9:
            run += 1
            worst_run = max(worst_run, run)
        else:
            run = 0
    s.max_consecutive_losses = worst_run

    return s
