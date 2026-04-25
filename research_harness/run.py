from __future__ import annotations

import argparse
from pathlib import Path

from .backtest import run_research_harness
from .config import HarnessConfig
from .reporting import write_artifacts


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description='Run the multi-agent quant research harness.')
  parser.add_argument('--symbols', nargs='+', default=['SPY', 'QQQ', 'GLD', 'TLT'])
  parser.add_argument('--start', default='2020-01-01')
  parser.add_argument('--end', default=None)
  parser.add_argument('--track', choices=['all', 'proposal', 'ml'], default='all')
  parser.add_argument('--sequence-length', type=int, default=20)
  parser.add_argument('--train-window', type=int, default=504)
  parser.add_argument('--covariance-window', type=int, default=60)
  parser.add_argument('--refit-every', type=int, default=21)
  parser.add_argument('--transaction-cost-bps', type=float, default=5.0)
  parser.add_argument('--output-dir', default='artifacts/research')
  parser.add_argument('--public-snapshot-path', default='public/project-snapshot.json')
  return parser


def main() -> int:
  parser = build_parser()
  args = parser.parse_args()
  config = HarnessConfig(
    symbols=tuple(args.symbols),
    start=args.start,
    end=args.end,
    track=args.track,
    sequence_length=args.sequence_length,
    train_window=args.train_window,
    covariance_window=args.covariance_window,
    refit_every=args.refit_every,
    transaction_cost_bps=args.transaction_cost_bps,
    output_dir=Path(args.output_dir),
    public_snapshot_path=Path(args.public_snapshot_path),
  )
  result = run_research_harness(config)
  paths = write_artifacts(result, config.output_dir, config.public_snapshot_path)

  print(
    f"Downloaded {result['data_summary']['rows']} trading days for "
    f"{', '.join(result['data_summary']['symbols'])}."
  )
  for track_key, track in result['tracks'].items():
    print(f"[{track_key}] {track['track_name']} | primary_metric={track['primary_metric']}")
    for name, payload in track['strategies'].items():
      metrics = payload['metrics']
      print(
        f"  {name:>20} | ann_return={metrics['annualized_return']:.2%} "
        f"log_wealth={metrics['cumulative_log_wealth']:.3f} "
        f"sharpe={metrics['sharpe']:.2f} max_dd={metrics['max_drawdown']:.2%}"
      )
  print(f"Artifacts written to: {paths['summary'].parent}")
  print(f"Frontend snapshot written to: {paths['public_snapshot']}")
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
