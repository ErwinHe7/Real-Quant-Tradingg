# Quant Research Harness

Quantitative trading project for the **COMS 4232 Advanced Algorithms** final project, extended with a second research track for systematic trading experiments.

## Why This Repo Exists

This repo has two tracks.

### 1. `proposal_core`

Course-project benchmark track:

- `Exponentiated Gradient (EG)`
- `Online Newton Step (ONS)`
- `Approximate Universal Portfolio`
- `Equal Weight (1/n)`
- `Momentum`
- `Mean Reversion`
- `BCRP` as the offline oracle benchmark

All methods share the same:

- historical market data
- long-only simplex constraints
- turnover-aware transaction-cost model
- evaluation pipeline

The primary metric is **transaction-cost-aware cumulative log-wealth**, with Sharpe, drawdown, and turnover as supporting diagnostics.

### 2. `ml_extension`

Extended research track:

- `Rolling Ridge Alpha`
- `Attention Sequence Alpha`
- `Blended Alpha Portfolio`
- deterministic transaction-cost-aware optimization

This track follows the standard quant pipeline:

- predictive signal model
- portfolio optimization
- cost / risk control
- deterministic execution path

## Multi-Agent Positioning

The agent layer is for research support, not autonomous execution:

- a feature / experiment agent proposes new ideas
- a validation agent checks leakage and overfit
- a risk agent reviews concentration, turnover, and guardrails
- a report agent writes the research memo

The execution path should stay deterministic even if the research loop becomes more agent-assisted.

## External Inspirations

This version was shaped using:

- the final project proposal and algorithm supplement
- [Open-Finance-Lab/AgenticTrading](https://github.com/Open-Finance-Lab/AgenticTrading)
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- [himself65/finance-skills](https://github.com/himself65/finance-skills)

This repo stays narrower than those references. The focus here is reproducible research, proposal compliance, and an implementation path that another engineer can continue.

## Project Shape

```text
frontend dashboard (React / Vite)
        |
        v
public/project-snapshot.json
        |
        v
Python research harness
  |- proposal_core algorithms
  |- ml_extension models
  |- deterministic optimizer
  |- reporting + agent briefs
```

## Run Locally

Install frontend dependencies:

```bash
npm install
```

Install Python research dependencies:

```bash
python -m pip install -r requirements-research.txt
```

Run the research pipeline:

```bash
npm run research:run
```

Run only one track if you want:

```bash
python -m research_harness.run --track proposal
python -m research_harness.run --track ml
```

Start the site locally:

```bash
npm run dev
```

Build the static site:

```bash
npm run build
```

## Artifacts

Running the harness writes:

- `artifacts/research/summary.json`
- `artifacts/research/research_report.md`
- `artifacts/research/proposal_core_metrics.csv`
- `artifacts/research/ml_extension_metrics.csv`
- `artifacts/research/daily_performance.csv`
- `artifacts/research/agent_feature_brief.md`
- `artifacts/research/agent_validation_brief.md`
- `artifacts/research/agent_risk_brief.md`
- `artifacts/research/agent_report_brief.md`
- `public/project-snapshot.json`

The frontend reads `public/project-snapshot.json`, so the GitHub page reflects the latest generated run.

## GitHub Pages

The Vite config uses a relative base path so the static build can be deployed cleanly to GitHub Pages. A sample Pages workflow is included in `.github/workflows/deploy-pages.yml`.

Recommended publishing flow:

1. Run `npm run research:run`
2. Verify `public/project-snapshot.json` updated
3. Run `npm run build`
4. Push to GitHub
5. Enable GitHub Pages with the included workflow

## Handoff Notes

If another engineer is continuing implementation, start with:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/HANDOFF.md](docs/HANDOFF.md)

## Important Warning

This project is for research and educational purposes. Backtests can be misleading, paper trading differs from live execution, and nothing here is investment advice.
