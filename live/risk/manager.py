"""
RiskManager — orchestrates all pre-trade checks and circuit breakers.

The manager is a pure function given its inputs: (target_weights, account,
market, history) → RiskOutcome.  State changes are applied to *history* by
the caller; no hidden mutable state lives here.

The deterministic execution rule (charter R4) is enforced here: the manager
approves or rejects weights; it never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

import pandas as pd

from .breakers import BreakerState, DrawdownBreaker, DailyLossBreaker, KillSwitch
from .checks import (
    check_buying_power,
    check_gross_leverage,
    check_min_position_notional,
    check_net_leverage,
    check_pdt_day_trade_counter,
    check_per_name_weight,
    check_per_sector_weight,
    check_position_count,
    check_short_locate,
)
from .limits import RiskLimits, DEFAULT_LIMITS
from .types import AccountState, CheckStatus, MarketState, RiskDecision, RiskHistory
from .vol_target import scale_to_vol_target

import numpy as np


@dataclass
class RiskOutcome:
    approved_weights: pd.Series
    decisions: list[RiskDecision]
    mode: Literal["trade", "halt", "liquidate"]

    @property
    def any_halt(self) -> bool:
        return any(d.is_halt or d.status == CheckStatus.REJECT for d in self.decisions)


class RiskManager:
    """
    Deterministic, stateless (given inputs) risk evaluation layer.

    Usage
    -----
    manager = RiskManager(limits=DEFAULT_LIMITS, kill_switch=ks)
    outcome = manager.evaluate(target_weights, account, market, history)
    if outcome.mode == "trade":
        place_orders(outcome.approved_weights)
    """

    def __init__(
        self,
        limits: RiskLimits = DEFAULT_LIMITS,
        kill_switch: KillSwitch | None = None,
        drawdown_breaker: DrawdownBreaker | None = None,
        daily_loss_breaker: DailyLossBreaker | None = None,
    ) -> None:
        self._limits = limits
        self._kill_switch = kill_switch or KillSwitch()
        self._drawdown_breaker = drawdown_breaker or DrawdownBreaker(
            max_dd_pct=limits.max_drawdown_from_hwm,
            cool_off_days=limits.drawdown_cool_off_days,
        )
        self._daily_loss_breaker = daily_loss_breaker or DailyLossBreaker(
            max_loss_pct=limits.max_daily_loss_pct
        )

    def evaluate(
        self,
        target_weights: pd.Series,
        account_state: AccountState,
        market_state: MarketState,
        history: RiskHistory,
        *,
        current_positions: pd.Series | None = None,
        equity_curve: pd.Series | None = None,
        realised_cov: pd.DataFrame | None = None,
    ) -> RiskOutcome:
        """
        Evaluate all risk checks and return approved weights + mode.

        Parameters
        ----------
        target_weights   : proposed weights from the strategy
        account_state    : current broker account snapshot
        market_state     : current market data
        history          : mutable risk state (updated in-place)
        current_positions: current live position weights (for PDT check)
        equity_curve     : recent equity series (for drawdown breaker)
        realised_cov     : for volatility targeting; if None, skip vol-target
        """
        decisions: list[RiskDecision] = []
        approved = target_weights.copy()

        # --- Kill switch check ---
        if self._kill_switch.is_engaged():
            reason = self._kill_switch.read_reason()
            decisions.append(RiskDecision(
                check_name="kill_switch",
                status=CheckStatus.HALT,
                reason=f"Kill switch engaged: {reason}",
            ))
            return RiskOutcome(
                approved_weights=pd.Series(0.0, index=target_weights.index),
                decisions=decisions,
                mode="halt",
            )

        # --- Circuit breakers ---
        if equity_curve is not None and not equity_curve.empty:
            dd_state = self._drawdown_breaker.update(equity_curve)
            if dd_state == BreakerState.ENGAGED:
                history.drawdown_breaker_engaged = True
                self._kill_switch.engage(
                    f"Drawdown breaker fired at {datetime.utcnow().isoformat()}"
                )
                decisions.append(RiskDecision(
                    check_name="drawdown_breaker",
                    status=CheckStatus.HALT,
                    reason="Drawdown from HWM exceeded limit; kill switch engaged",
                ))
                return RiskOutcome(
                    approved_weights=pd.Series(0.0, index=target_weights.index),
                    decisions=decisions,
                    mode="halt",
                )

        daily_loss_state = self._daily_loss_breaker.update(history.day_pnl, account_state.equity_usd)
        if daily_loss_state == BreakerState.ENGAGED:
            history.daily_loss_breaker_engaged = True
            decisions.append(RiskDecision(
                check_name="daily_loss_breaker",
                status=CheckStatus.HALT,
                reason=f"Daily loss ${history.day_pnl:.2f} exceeded limit",
            ))
            return RiskOutcome(
                approved_weights=pd.Series(0.0, index=target_weights.index),
                decisions=decisions,
                mode="halt",
            )

        # --- Pre-trade checks ---
        d = check_short_locate(approved, allow_short=self._limits.allow_short)
        decisions.append(d)
        if d.status == CheckStatus.REJECT:
            # Force zero on all shorts
            approved = approved.clip(lower=0.0)

        # Extreme concentration check: >5× per-name cap is a rogue signal
        max_abs_weight = float(approved.abs().max()) if len(approved) > 0 else 0.0
        if max_abs_weight > 5.0 * self._limits.max_per_name_pct:
            reason = (
                f"Extreme position concentration: max weight {max_abs_weight:.2f} "
                f"is >5× per-name cap {self._limits.max_per_name_pct:.2%}. "
                "Likely a rogue strategy or calculation error."
            )
            self._kill_switch.engage(reason)
            decisions.append(RiskDecision(
                check_name="rogue_concentration",
                status=CheckStatus.HALT,
                reason=reason,
            ))
            return RiskOutcome(
                approved_weights=pd.Series(0.0, index=target_weights.index),
                decisions=decisions,
                mode="halt",
            )

        d = check_per_name_weight(approved, self._limits.max_per_name_pct)
        decisions.append(d)
        if d.status == CheckStatus.REJECT:
            # Scale down violating names
            approved = approved.clip(upper=self._limits.max_per_name_pct)
            total = approved.sum()
            if total > 0:
                approved = approved / total

        d = check_per_sector_weight(approved, market_state.sector_map, self._limits.max_per_sector_pct)
        decisions.append(d)

        d = check_gross_leverage(approved, self._limits.max_gross_leverage)
        decisions.append(d)
        if d.status == CheckStatus.REJECT:
            gross = approved.abs().sum()
            if gross > 0:
                approved = approved * (self._limits.max_gross_leverage / gross)

        d = check_net_leverage(approved, self._limits.max_net_leverage)
        decisions.append(d)

        d = check_position_count(approved, self._limits.max_positions)
        decisions.append(d)
        if d.status == CheckStatus.REJECT:
            # Keep only the top-N by absolute weight
            top_n = approved.abs().nlargest(self._limits.max_positions).index
            approved = approved.reindex(top_n)
            total = approved.abs().sum()
            if total > 0:
                approved = approved / total

        d = check_min_position_notional(approved, account_state.equity_usd, self._limits.min_position_notional_usd)
        decisions.append(d)
        if d.status == CheckStatus.WARN and d.detail.get("symbols"):
            # Zero out tiny positions
            for sym in d.detail["symbols"]:
                if sym in approved.index:
                    approved[sym] = 0.0

        d = check_buying_power(approved, account_state, market_state)
        decisions.append(d)

        if current_positions is not None:
            d = check_pdt_day_trade_counter(
                account_state, approved, current_positions, self._limits.max_day_trades_per_5d
            )
            decisions.append(d)
            if d.status == CheckStatus.REJECT:
                # Zero out new opens that triggered the PDT check
                for sym in d.detail.get("would_open", []):
                    if sym in approved.index:
                        approved[sym] = 0.0

        # --- Volatility targeting ---
        if realised_cov is not None and not realised_cov.empty:
            approved = scale_to_vol_target(
                approved,
                realised_cov,
                target_annual_vol=self._limits.target_annual_vol,
                max_gross=self._limits.max_gross_leverage,
            )

        # Check if any hard reject fired
        hard_rejects = [d for d in decisions if d.status in (CheckStatus.REJECT, CheckStatus.HALT)]
        if hard_rejects:
            mode: Literal["trade", "halt", "liquidate"] = "halt"
        else:
            mode = "trade"

        return RiskOutcome(approved_weights=approved, decisions=decisions, mode=mode)
