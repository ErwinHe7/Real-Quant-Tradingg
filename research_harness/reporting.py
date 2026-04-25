from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd


def _track_metrics_frame(track: dict[str, object]) -> pd.DataFrame:
  rows = []
  for key, payload in track['strategies'].items():
    row = {'strategy': key}
    row.update(payload['definition'])
    row.update(payload['metrics'])
    rows.append(row)
  ascending = False
  return pd.DataFrame(rows).sort_values(track['primary_metric'], ascending=ascending)


def _public_payload(result: dict[str, object]) -> dict[str, object]:
  tracks = {}
  for track_key, track in result['tracks'].items():
    tracks[track_key] = {
      'track_key': track['track_key'],
      'track_name': track['track_name'],
      'primary_metric': track['primary_metric'],
      'leader': track['leader'],
      'benchmark': track.get('benchmark'),
      'regime_method': track.get('regime_method'),
      'strategies': track['strategies'],
    }

  return {
    'config': result['config'],
    'data_summary': result['data_summary'],
    'architecture': result['architecture'],
    'tracks': tracks,
    'recommended_path': result['recommended_path'],
  }


def _clean_json_value(value: object) -> object:
  if value is None:
    return None
  if isinstance(value, float) and math.isnan(value):
    return None
  try:
    if pd.isna(value):
      return None
  except TypeError:
    pass
  return value


def _timeseries_payload(result: dict[str, object]) -> dict[str, object]:
  tracks: dict[str, object] = {}
  for track_key, track in result['tracks'].items():
    track_series: dict[str, list[dict[str, object]]] = {}
    for strategy_key in track['strategies']:
      frame = (
        result['daily_performance']
        .loc[
          (result['daily_performance']['track'] == track_key)
          & (result['daily_performance']['strategy'] == strategy_key)
        ]
        .sort_values('date')
      )
      rows: list[dict[str, object]] = []
      for record in frame.to_dict(orient='records'):
        rows.append(
          {
            'date': _clean_json_value(record['date']),
            'decision_date': _clean_json_value(record.get('decision_date')),
            'equity': _clean_json_value(record['equity']),
            'gross_factor': _clean_json_value(record['gross_factor']),
            'net_simple_return': _clean_json_value(record['net_simple_return']),
            'turnover': _clean_json_value(record['turnover']),
            'cost_paid': _clean_json_value(record['cost_paid']),
            'regime': _clean_json_value(record.get('regime')),
            'top_symbol': _clean_json_value(record.get('top_symbol')),
          }
        )
      track_series[strategy_key] = rows
    tracks[track_key] = track_series
  return {'tracks': tracks}


def _project_report(result: dict[str, object]) -> str:
  lines = [
    '# Quant Trading Project Report',
    '',
    f"- Universe: {', '.join(result['data_summary']['symbols'])}",
    f"- Data range: {result['data_summary']['start']} to {result['data_summary']['end']}",
    f"- Trading days: {result['data_summary']['rows']}",
    '',
    '## Recommended Positioning',
    '',
    '- `proposal_core` is the coursework-safe benchmark track aligned to the Columbia proposal.',
    '- `ml_extension` is the GitHub / real-world extension track built around deterministic optimization plus modern signal models.',
    '- The live path should remain deterministic even if research becomes multi-agent.',
    '',
  ]

  for track_key, track in result['tracks'].items():
    metrics = _track_metrics_frame(track)
    leader = metrics.iloc[0]
    lines.extend(
      [
        f"## {track['track_name']}",
        '',
        f"- Primary metric: `{track['primary_metric']}`",
        f"- Leader: `{leader['name']}`",
        f"- Track key: `{track_key}`",
        '',
      ]
    )
    if track.get('benchmark'):
      lines.append(f"- Offline benchmark: `{track['benchmark']}`")
      lines.append('')
    for _, row in metrics.iterrows():
      lines.extend(
        [
          f"### {row['name']}",
          f"- Family: {row['family']}",
          f"- Annualized return: {row['annualized_return']:.2%}",
          f"- Sharpe: {row['sharpe']:.2f}",
          f"- Max drawdown: {row['max_drawdown']:.2%}",
          f"- Average turnover: {row['avg_turnover']:.2%}",
          f"- Cost drag: {row['cost_drag']:.2%}",
          '',
        ]
      )

  lines.extend(
    [
      '## Architecture',
      '',
      'Core principles:',
    ]
  )
  lines.extend([f"- {item}" for item in result['architecture']['principles']])
  lines.append('')
  lines.append('Agent roles:')
  lines.extend(
    [
      f"- {role['title']}: {role['purpose']}"
      for role in result['architecture']['agent_roles']
    ]
  )
  lines.append('')
  return '\n'.join(lines)


def _feature_agent_brief(result: dict[str, object]) -> str:
  return '\n'.join(
    [
      '# Feature Agent Brief',
      '',
      'Focus on experiments that improve alpha quality without violating the proposal-core rules.',
      '',
      'Priority queue:',
      '- Add sector ETF and factor ETF universes as controlled expansions.',
      '- Add residual momentum and rolling beta features to the ML extension track.',
      '- Test different momentum / mean-reversion windows and report sensitivity, not just the best run.',
      '- Keep proposal-core algorithms training-free and online by construction.',
    ]
  )


def _validation_agent_brief(result: dict[str, object]) -> str:
  return '\n'.join(
    [
      '# Validation Agent Brief',
      '',
      'This project now has two tracks. Validate both separately.',
      '',
      'Proposal-core checks:',
      '- Verify EG, ONS, Universal Portfolio, Equal Weight, Momentum, Mean Reversion, and BCRP all share the same market data and turnover model.',
      '- Verify BCRP is treated as an oracle benchmark, not a deployable live strategy.',
      '',
      'ML-extension checks:',
      '- Verify training windows stop before the decision date.',
      '- Stress transaction costs upward and compare strategy ranking changes.',
      '- Confirm the optimizer remains deterministic even if agents generate research ideas.',
    ]
  )


def _risk_agent_brief(result: dict[str, object]) -> str:
  lines = [
    '# Risk Agent Brief',
    '',
    'Review concentration, turnover, and drawdown at the track and strategy level.',
    '',
  ]
  for track in result['tracks'].values():
    metrics = _track_metrics_frame(track)
    leader = metrics.iloc[0]
    lines.extend(
      [
        f"## {track['track_name']}",
        f"- Current leader: {leader['name']}",
        f"- Max drawdown: {leader['max_drawdown']:.2%}",
        f"- Average turnover: {leader['avg_turnover']:.2%}",
        f"- Cost drag: {leader['cost_drag']:.2%}",
        '',
      ]
    )
  lines.extend(
    [
      'Non-negotiable controls:',
      '- long-only and capped-position constraints',
      '- explicit transaction cost model',
      '- paper trading before live trading',
      '- deterministic execution path',
    ]
  )
  return '\n'.join(lines)


def _report_agent_brief(result: dict[str, object]) -> str:
  return '\n'.join(
    [
      '# Report Agent Brief',
      '',
      'Write updates for GitHub and reviewers.',
      '',
      'Narrative checklist:',
      '- explain why the repo has both a proposal-core track and an industry-extension track',
      '- state that the proposal-core track is the grading-safe benchmark path',
      '- state that the ML track is the practical extension toward real systematic trading',
      '- emphasize that the agent layer supports research and review, not autonomous live order placement',
    ]
  )


def write_artifacts(
  result: dict[str, object],
  output_dir: Path,
  public_snapshot_path: Path,
) -> dict[str, Path]:
  output_dir.mkdir(parents=True, exist_ok=True)
  public_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
  public_timeseries_path = public_snapshot_path.with_name('project-timeseries.json')

  summary_path = output_dir / 'summary.json'
  daily_path = output_dir / 'daily_performance.csv'
  report_path = output_dir / 'research_report.md'
  feature_path = output_dir / 'agent_feature_brief.md'
  validation_path = output_dir / 'agent_validation_brief.md'
  risk_path = output_dir / 'agent_risk_brief.md'
  report_agent_path = output_dir / 'agent_report_brief.md'

  public_payload = _public_payload(result)
  summary_path.write_text(json.dumps(public_payload, indent=2, allow_nan=False), encoding='utf-8')
  public_snapshot_path.write_text(json.dumps(public_payload, indent=2, allow_nan=False), encoding='utf-8')
  public_timeseries_path.write_text(
    json.dumps(_timeseries_payload(result), indent=2, allow_nan=False),
    encoding='utf-8',
  )
  result['daily_performance'].to_csv(daily_path, index=False)
  report_path.write_text(_project_report(result), encoding='utf-8')
  feature_path.write_text(_feature_agent_brief(result), encoding='utf-8')
  validation_path.write_text(_validation_agent_brief(result), encoding='utf-8')
  risk_path.write_text(_risk_agent_brief(result), encoding='utf-8')
  report_agent_path.write_text(_report_agent_brief(result), encoding='utf-8')

  track_metric_paths: dict[str, Path] = {}
  for track_key, track in result['tracks'].items():
    metrics_frame = _track_metrics_frame(track)
    metrics_path = output_dir / f'{track_key}_metrics.csv'
    metrics_frame.to_csv(metrics_path, index=False)
    track_metric_paths[track_key] = metrics_path

  return {
    'summary': summary_path,
    'daily': daily_path,
    'report': report_path,
    'feature_agent': feature_path,
    'validation_agent': validation_path,
    'risk_agent': risk_path,
    'report_agent': report_agent_path,
    'public_snapshot': public_snapshot_path,
    'public_timeseries': public_timeseries_path,
    **track_metric_paths,
  }
