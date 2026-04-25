from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class HarnessConfig:
  symbols: tuple[str, ...] = ('SPY', 'QQQ', 'GLD', 'TLT')
  start: str = '2020-01-01'
  end: str | None = None
  track: str = 'all'
  primary_metric: str = 'cumulative_log_wealth'
  eg_eta: float = 12.0
  ons_beta: float = 1.0
  ons_epsilon: float = 1.0
  universal_samples: int = 400
  universal_dirichlet_concentration: float = 1.0
  momentum_window: int = 20
  mean_reversion_window: int = 10
  top_k: int = 2
  regime_window: int = 20
  sequence_length: int = 20
  train_window: int = 504
  covariance_window: int = 60
  refit_every: int = 21
  ridge_alpha: float = 18.0
  attention_hidden_size: int = 8
  attention_epochs: int = 35
  attention_learning_rate: float = 0.01
  attention_l2: float = 0.0005
  attention_max_samples: int = 900
  transaction_cost_bps: float = 5.0
  risk_aversion: float = 8.0
  turnover_penalty: float = 0.35
  max_weight: float = 0.55
  random_seed: int = 7
  output_dir: Path = Path('artifacts/research')
  public_snapshot_path: Path = Path('public/project-snapshot.json')

  def to_dict(self) -> dict[str, object]:
    data = asdict(self)
    data['output_dir'] = str(self.output_dir)
    data['public_snapshot_path'] = str(self.public_snapshot_path)
    return data
