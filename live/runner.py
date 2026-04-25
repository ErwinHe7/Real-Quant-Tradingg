"""
Live/paper-trading runner.

Usage:
    python -m live.runner --strategy ons --broker paper
    python -m live.runner --strategy ons --broker moomoo-paper

The runner:
  1. Loads data from the cache for the strategy universe
  2. Instantiates the strategy
  3. Instantiates the chosen broker
  4. Runs the OMS event loop
  5. Writes session logs and end-of-day report

This file is the ONLY place where MoomooBroker(env='live') may legally be
constructed (enforced in Phase 6 via CI grep).  In Phase 5, only env='paper'
is allowed.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _build_strategy(strategy_name: str, symbols: tuple[str, ...]):
    """Build a strategy callable that returns target weights."""
    from research_harness.config import HarnessConfig
    from research_harness.data import download_market_data
    from research_harness.online_portfolio import (
        OnlineNewtonStepStrategy,
        ExponentiatedGradientStrategy,
        normalize_weights,
    )

    config = HarnessConfig(symbols=symbols)
    market = download_market_data(symbols, config.start, None)
    returns = market.returns.dropna()
    gross_returns = 1.0 + returns

    if strategy_name == "ons":
        strategy_obj = OnlineNewtonStepStrategy(
            n_assets=len(symbols), beta=config.ons_beta, epsilon=config.ons_epsilon
        )
    elif strategy_name == "eg":
        strategy_obj = ExponentiatedGradientStrategy(n_assets=len(symbols), eta=config.eg_eta)
    else:
        raise ValueError(f"Unknown strategy '{strategy_name}'. Use 'ons' or 'eg'.")

    # Warm up the strategy on historical data
    history = []
    for _, row in gross_returns.iterrows():
        gv = row.to_numpy(dtype=float)
        weights = normalize_weights(strategy_obj.allocate(np.asarray(history)))
        strategy_obj.update(weights, gv)
        history.append(gv)

    logger.info("Strategy '%s' warmed up on %d days of history", strategy_name, len(history))

    def strategy_fn() -> pd.Series:
        """Return latest weights from the warmed-up strategy."""
        arr = np.asarray(history) if history else np.zeros((1, len(symbols)))
        w = normalize_weights(strategy_obj.allocate(arr))
        return pd.Series(w, index=list(symbols))

    return strategy_fn


def _build_broker(broker_name: str, state_root: Path, symbols: tuple[str, ...] | None = None):
    """Build the requested broker."""
    if broker_name == "paper":
        from live.broker.paper import PaperBroker
        # Wire up cached prices so the broker uses real last-close prices
        price_feed = None
        adv_feed = None
        if symbols:
            try:
                from research_harness.data_store import load_prices_wide
                from pathlib import Path as _Path
                _cache = _Path("data/cache")
                _close = load_prices_wide(symbols, "2020-01-01", None, field="adj_close", cache_root=_cache)
                _vol = load_prices_wide(symbols, "2020-01-01", None, field="volume", cache_root=_cache)
                _last_close = _close.iloc[-1].to_dict() if not _close.empty else {}
                _last_vol = _vol.iloc[-1].to_dict() if not _vol.empty else {}
                _last_high = load_prices_wide(symbols, "2020-01-01", None, field="high", cache_root=_cache).iloc[-1].to_dict() if not _close.empty else {}
                _last_low = load_prices_wide(symbols, "2020-01-01", None, field="low", cache_root=_cache).iloc[-1].to_dict() if not _close.empty else {}
                _adv = {s: float(_vol[s].rolling(20).mean().iloc[-1]) * float(_last_close.get(s, 100.0)) for s in symbols if s in _vol.columns}

                def price_feed(symbol: str) -> dict:
                    p = _last_close.get(symbol, 100.0)
                    return {
                        "open": p, "high": _last_high.get(symbol, p * 1.01),
                        "low": _last_low.get(symbol, p * 0.99),
                        "close": p, "volume": _last_vol.get(symbol, 1e6),
                    }

                def adv_feed(symbol: str) -> float:
                    return _adv.get(symbol, 1e7)

                logger.info("PaperBroker: using cached last-close prices (%d symbols)", len(_last_close))
            except Exception as exc:
                logger.warning("Could not load cached prices for PaperBroker: %s — using $100 stub", exc)

        return PaperBroker(state_root=state_root, price_feed=price_feed, adv_feed=adv_feed)
    elif broker_name == "moomoo-paper":
        from live.broker.moomoo import MoomooBroker
        return MoomooBroker(env="paper")
    else:
        raise ValueError(f"Unknown broker '{broker_name}'. Use 'paper' or 'moomoo-paper'.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Live/paper-trading runner")
    parser.add_argument("--strategy", default="ons", choices=["ons", "eg"])
    parser.add_argument("--broker", default="paper", choices=["paper", "moomoo-paper"])
    parser.add_argument("--symbols", nargs="+", default=["GLD", "QQQ", "SPY", "TLT"])
    parser.add_argument("--ticks", type=int, default=None,
                        help="Max ticks to run (None = infinite, use for testing)")
    parser.add_argument("--state-root", default="live/state")
    args = parser.parse_args(argv)

    symbols = tuple(args.symbols)
    state_root = Path(args.state_root)
    session_dir = state_root / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting runner: strategy=%s broker=%s symbols=%s", args.strategy, args.broker, symbols)

    # Kill switch
    from live.risk.breakers import KillSwitch
    ks = KillSwitch(state_root=state_root)
    if ks.is_engaged():
        logger.error("Kill switch is engaged (%s). Disengage before starting.", ks.read_reason())
        return 1

    # Build components
    strategy_fn = _build_strategy(args.strategy, symbols)
    broker = _build_broker(args.broker, state_root, symbols=symbols)

    from live.risk.manager import RiskManager
    from live.risk.limits import DEFAULT_LIMITS
    risk_mgr = RiskManager(limits=DEFAULT_LIMITS, kill_switch=ks)

    from live.oms.engine import OMSEngine
    engine = OMSEngine(
        strategy=strategy_fn,
        broker=broker,
        risk_manager=risk_mgr,
        state_path=state_root / "oms_state.json",
        kill_switch=ks,
        tick_interval_s=15 * 60,
        reconcile_every=4,
    )

    from live.monitor.health import Heartbeat
    from live.monitor.notify import send_alert
    hb = Heartbeat(state_root / "heartbeat.json")

    session_log = session_dir / f"{date.today().isoformat()}.jsonl"

    def _on_tick() -> None:
        hb.beat({"strategy": args.strategy, "broker": args.broker})
        account = broker.account()
        entry = json.dumps({
            "ts": datetime.utcnow().isoformat(),
            "equity": account.equity_usd,
            "cash": account.cash_usd,
        })
        with session_log.open("a") as f:
            f.write(entry + "\n")

    engine._state.save = _on_tick  # type: ignore[method-assign]

    try:
        engine.run_session(max_ticks=args.ticks)
    except Exception as exc:
        logger.error("Runner crashed: %s", exc)
        send_alert("Runner crash", str(exc))
        ks.engage(f"Runner crashed: {exc}")
        return 1
    finally:
        if hasattr(broker, "close"):
            broker.close()

    # End-of-day summary
    account = broker.account()
    summary = {
        "date": date.today().isoformat(),
        "strategy": args.strategy,
        "broker": args.broker,
        "symbols": list(symbols),
        "final_equity": account.equity_usd,
        "cash": account.cash_usd,
        "ticks": engine._tick_count,
    }
    summary_path = state_root / "sessions" / f"{date.today().isoformat()}-summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Session summary written to %s", summary_path)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
