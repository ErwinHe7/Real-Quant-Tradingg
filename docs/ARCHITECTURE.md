# Architecture

## Recommended Mental Model

This repo is intentionally split into two layers:

1. **Proposal core**
2. **Industry extension**

The proposal core is the coursework backbone. The industry extension is the path that makes the repo worth keeping after the class.

## Layer Map

### Frontend

The React / Vite app is a static project site for GitHub Pages.

Its job is to:

- explain the project clearly
- display the latest benchmark results
- show the system architecture and implementation posture

It reads from:

- `public/project-snapshot.json`

### Research Harness

The Python backend is the actual computation layer.

Main modules:

- `research_harness/data.py`
  market data download and normalization
- `research_harness/online_portfolio.py`
  EG, ONS, Approximate Universal Portfolio, Equal Weight, Momentum, Mean Reversion, BCRP, and proposal diagnostics
- `research_harness/features.py`
  handcrafted features for the extension track
- `research_harness/models.py`
  ridge baseline and lightweight attention sequence model
- `research_harness/optimizer.py`
  deterministic transaction-cost-aware optimizer
- `research_harness/ml_extension.py`
  extension-track walk-forward simulation
- `research_harness/backtest.py`
  top-level orchestration across tracks
- `research_harness/reporting.py`
  reports, CSVs, and agent briefs

## Deterministic Trading Principle

The most important architectural rule is:

> agents may guide research, but they must not directly own live trade execution

Recommended production posture:

1. agents propose experiments
2. deterministic code runs the backtest
3. validation checks assumptions
4. risk checks constraints
5. paper trading runs next
6. only then should a deterministic execution engine submit orders

## Why Two Tracks

### Proposal core

This track answers the class question:

- when online portfolio algorithms face the same market and cost model, what properties of their update rules explain performance differences?

### Industry extension

This track answers the longer-term engineering question:

- how do you evolve from an academic comparison into a credible quant research system?

## External Influences

This architecture borrows selectively:

- **AgenticTrading**: layered orchestration and memory-oriented thinking
- **TradingAgents**: role decomposition across research, risk, and decision-making
- **finance-skills**: reusable skill / tool packaging mindset

What this repo does **not** copy is the idea that everything should be an LLM agent. The optimizer, cost model, and portfolio simulator remain ordinary deterministic code.
