from __future__ import annotations

import pandas as pd

from .config import HarnessConfig
from .data import download_market_data
from .features import build_feature_store
from .ml_extension import run_ml_extension_track
from .online_portfolio import (
  build_online_strategies,
  classify_volatility_regime,
  compute_bcrp_weights,
  simulate_constant_rebalanced_portfolio,
  simulate_online_strategy,
)


def _strategy_payload(strategy_result) -> dict[str, object]:
  return {
    'definition': {
      'key': strategy_result.definition.key,
      'name': strategy_result.definition.name,
      'family': strategy_result.definition.family,
      'description': strategy_result.definition.description,
      'complexity': strategy_result.definition.complexity,
      'theory': strategy_result.definition.theory,
      'parameters': strategy_result.definition.parameters,
    },
    'metrics': strategy_result.metrics,
    'latest_weights': strategy_result.latest_weights,
  }


def _architecture_payload() -> dict[str, object]:
  return {
    'principles': [
      'Keep the live path deterministic even if the research loop becomes agentic.',
      'Separate course-grade online portfolio benchmarks from industry-style alpha extensions.',
      'Treat transaction costs, turnover, and risk controls as first-class components.',
      'Generate artifacts that agents and human reviewers can both consume.',
    ],
    'agent_roles': [
      {
        'id': 'feature',
        'title': 'Feature and Experiment Agent',
        'purpose': 'Propose new factors, data joins, and ablations for the research queue.',
      },
      {
        'id': 'validation',
        'title': 'Validation Agent',
        'purpose': 'Look for leakage, parameter overfit, benchmark drift, and unrealistic assumptions.',
      },
      {
        'id': 'risk',
        'title': 'Risk and Constraints Agent',
        'purpose': 'Review concentration, turnover, cost drag, and live trading guardrails.',
      },
      {
        'id': 'report',
        'title': 'Research Report Agent',
        'purpose': 'Convert runs into short memos, experiment logs, and GitHub-friendly updates.',
      },
    ],
    'reference_inspirations': [
      'The Columbia proposal defines the online portfolio benchmark track.',
      'Open-Finance-Lab/AgenticTrading contributes the layered orchestrator and memory-agent perspective.',
      'TauricResearch/TradingAgents contributes the desk-style role decomposition across analysts, traders, and risk.',
      'himself65/finance-skills contributes the idea of reusable research skills and tool packaging.',
    ],
  }


def run_research_harness(config: HarnessConfig) -> dict[str, object]:
  market = download_market_data(config.symbols, config.start, config.end)
  returns = market.returns.dropna()
  gross_returns = 1.0 + returns
  regimes = classify_volatility_regime(returns, config.regime_window).reindex(gross_returns.index).fillna('warmup')
  store = build_feature_store(market, config.symbols)
  tracks: dict[str, object] = {}
  all_daily_frames: list[pd.DataFrame] = []

  if config.track in ('all', 'proposal'):
    bcrp_weights = compute_bcrp_weights(gross_returns.to_numpy(dtype=float))
    bcrp_result = simulate_constant_rebalanced_portfolio(
      key='bcrp',
      name='Best Constant Rebalanced Portfolio',
      weights=bcrp_weights,
      gross_returns=gross_returns,
      regimes=regimes,
      symbols=config.symbols,
    )
    online_results = {
      'bcrp': bcrp_result,
    }
    for strategy in build_online_strategies(
      n_assets=len(config.symbols),
      eg_eta=config.eg_eta,
      ons_beta=config.ons_beta,
      ons_epsilon=config.ons_epsilon,
      universal_samples=config.universal_samples,
      universal_concentration=config.universal_dirichlet_concentration,
      momentum_window=config.momentum_window,
      mean_reversion_window=config.mean_reversion_window,
      top_k=min(config.top_k, len(config.symbols)),
      random_seed=config.random_seed,
    ):
      result = simulate_online_strategy(
        strategy=strategy,
        gross_returns=gross_returns,
        regimes=regimes,
        transaction_cost_bps=config.transaction_cost_bps,
        benchmark_log_wealth=bcrp_result.metrics['cumulative_log_wealth'],
        symbols=config.symbols,
      )
      online_results[strategy.definition.key] = result

    deployable = [
      result for key, result in online_results.items() if key != 'bcrp'
    ]
    proposal_leader = max(deployable, key=lambda item: item.metrics['cumulative_log_wealth'])
    proposal_daily = pd.concat(
      [result.daily_records for result in online_results.values()],
      ignore_index=True,
    )
    all_daily_frames.append(proposal_daily)
    tracks['proposal_core'] = {
      'track_key': 'proposal_core',
      'track_name': 'Advanced Algorithms Core Benchmark',
      'primary_metric': config.primary_metric,
      'leader': proposal_leader.definition.key,
      'benchmark': 'bcrp',
      'strategies': {
        key: _strategy_payload(result) for key, result in online_results.items()
      },
      'daily_performance': proposal_daily,
      'regime_method': '20-day equal-weight realized volatility above or below the sample median',
    }

  if config.track in ('all', 'ml'):
    ml_track = run_ml_extension_track(
      market_returns=returns,
      store=store,
      config=config,
      regimes=regimes,
    )
    all_daily_frames.append(ml_track['daily_performance'])
    tracks['ml_extension'] = {
      'track_key': ml_track['track_key'],
      'track_name': ml_track['track_name'],
      'primary_metric': ml_track['primary_metric'],
      'leader': ml_track['leader'],
      'strategies': {
        key: _strategy_payload(result) for key, result in ml_track['strategies'].items()
      },
      'daily_performance': ml_track['daily_performance'],
    }

  return {
    'config': config.to_dict(),
    'data_summary': {
      'start': gross_returns.index[0].strftime('%Y-%m-%d'),
      'end': gross_returns.index[-1].strftime('%Y-%m-%d'),
      'rows': len(gross_returns),
      'symbols': list(config.symbols),
    },
    'architecture': _architecture_payload(),
    'tracks': tracks,
    'daily_performance': pd.concat(all_daily_frames, ignore_index=True) if all_daily_frames else pd.DataFrame(),
    'recommended_path': [
      'Use the proposal_core track as the coursework evaluation path.',
      'Use the ml_extension track as the GitHub / industry extension path.',
      'Paper trade before any live deployment and keep execution deterministic.',
    ],
  }
