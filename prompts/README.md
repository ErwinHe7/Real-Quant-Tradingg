# Agent Prompt Library — Path To A Working Retail Quant System

This directory contains self-contained prompts intended to be handed to a fresh
Claude Code agent (or any equivalent code agent). Each prompt assumes the agent
has **no prior context** beyond reading the prompt file and the repository.

## Honest Framing (Read This First)

The owner of this repo has asked for an "industrial-grade, Jane-Street-level"
quant trading system. That phrase is aspirational, not literal. The achievable
target for a single-developer retail account on moomoo is:

- a research stack with statistically defensible backtests,
- a cost / risk / execution layer with the same architectural rigor a small
  prop firm would demand,
- a paper-trading adapter that runs unattended for months,
- a small-capital live deployment gated behind explicit human approval.

It is **not** a market-making engine, an HFT platform, or a system that
"beats Jane Street". Any agent that claims those things in code, comments,
docstrings, or commit messages is hallucinating and must be corrected.

## Mandatory Reading For Every Agent

Every phase prompt requires the executing agent to have read, in order:

1. `prompts/00-agent-charter.md` — non-negotiable rules, anti-patterns
2. `README.md` — repo purpose
3. `docs/ARCHITECTURE.md` — track separation, deterministic execution rule
4. `docs/HANDOFF.md` — what previous engineers said is left
5. The phase prompt itself

If the agent has not internalised the charter, it will generate plausible-looking
code that fails on real data. This is the single most common failure mode.

## Phase Order

Phases must be completed in order. Each phase has acceptance criteria; the next
phase assumes the previous one is green.

| Phase | File                                  | Purpose                                  |
| ----- | ------------------------------------- | ---------------------------------------- |
| 1     | (already done — see HANDOFF)          | moomoo skill, venv, smoke test           |
| 2     | `phase-2-data-layer.md`               | cached historical data + realtime feed   |
| 3     | `phase-3-strategy-research.md`        | universe expansion, sample-out validation|
| 4     | `phase-4-risk-controls.md`            | Kelly, vol-target, drawdown breaker      |
| 5     | `phase-5-paper-trading.md`            | moomoo paper-trading adapter + OMS       |
| 6     | `phase-6-live-gating.md`              | go-live gates, monitoring, kill switch   |
| 7     | `phase-7-performance-critical.md`     | (optional) Rust/C++ hot paths            |

## How To Run A Phase

Hand the chosen phase file to a fresh agent with a prompt like:

```
Read prompts/00-agent-charter.md and prompts/phase-N-<name>.md.
Execute the phase. Stop at the acceptance-criteria checkpoint and report.
Do not proceed to the next phase.
```

One phase per agent run keeps the blast radius bounded and makes review
tractable.

## Anti-Goals

These are not goals of this project, regardless of what the owner says in
casual conversation:

- "beat Jane Street" / "outperform institutional desks"
- "guaranteed profit" / "let me invest real money and earn"
- "fully autonomous trading with no human oversight"
- year-1 returns above ~25%; if a backtest shows more, assume a bug

If a phase appears to require an anti-goal, stop and flag it.
