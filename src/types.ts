export type AssetId = 'SPY' | 'QQQ' | 'GLD' | 'TLT'

export type StrategyId =
  | 'buy-hold'
  | 'momentum'
  | 'mean-reversion'
  | 'ucb'
  | 'exp3'

export interface AssetMeta {
  id: AssetId
  label: string
  accent: string
  description: string
  volatility: 'Low' | 'Medium' | 'High'
}

export interface MarketPoint {
  index: number
  date: string
  regime: string
  note: string
  prices: Record<AssetId, number>
  returns: Record<AssetId, number>
}

export interface StrategyDefinition {
  id: StrategyId
  name: string
  family: string
  description: string
  complexity: string
  guarantee: string
  thesis: string
}

export interface DecisionLogEntry {
  index: number
  decisionDate: string
  executionDate: string
  regime: string
  note: string
  selectedAsset: AssetId
  reason: string
  grossReturn: number
  realizedReturn: number
  switchCost: number
  switched: boolean
  equity: number
}

export interface StrategyMetrics {
  finalValue: number
  netReturn: number
  grossReturn: number
  sharpe: number
  maxDrawdown: number
  turnover: number
  winRate: number
  regretProxy: number
  minEquity: number
}

export interface HindsightSummary {
  bestAsset: AssetId
  finalValue: number
  netReturn: number
}

export interface SimulationResult {
  definition: StrategyDefinition
  metrics: StrategyMetrics
  decisionLog: DecisionLogEntry[]
  equityCurve: number[]
  timeline: MarketPoint[]
}
