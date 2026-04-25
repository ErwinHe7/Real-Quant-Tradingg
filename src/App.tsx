import { useEffect, useState } from 'react'
import './App.css'

type ViewKey = 'leaderboard' | 'dashboard' | 'artifacts' | 'tasks' | 'learning'
type TrackKey = 'proposal_core' | 'ml_extension'

interface StrategyMetrics {
  final_wealth: number
  cumulative_return: number
  cumulative_log_wealth: number
  annualized_return: number
  sharpe: number
  max_drawdown: number
  avg_turnover: number
  cost_drag: number
  hit_rate: number
  high_vol_avg_return: number
  low_vol_avg_return: number
  regret_vs_bcrp: number
}

interface StrategyDefinition {
  key: string
  name: string
  family: string
  description: string
  complexity: string
  theory: string
  parameters: Record<string, number | string>
}

interface StrategySnapshot {
  definition: StrategyDefinition
  metrics: StrategyMetrics
  latest_weights: Record<string, number>
}

interface TrackSnapshot {
  track_key: TrackKey
  track_name: string
  primary_metric: string
  leader: string
  benchmark?: string | null
  regime_method?: string | null
  strategies: Record<string, StrategySnapshot>
}

interface AgentRole {
  id: string
  title: string
  purpose: string
}

interface ProjectSnapshot {
  config: {
    symbols: string[]
    transaction_cost_bps: number
    primary_metric: string
  } & Record<string, unknown>
  data_summary: {
    start: string
    end: string
    rows: number
    symbols: string[]
  }
  architecture: {
    principles: string[]
    agent_roles: AgentRole[]
    reference_inspirations: string[]
  }
  tracks: Record<TrackKey, TrackSnapshot>
  recommended_path: string[]
}

interface SeriesPoint {
  date: string
  decision_date?: string | null
  equity: number
  gross_factor: number
  net_simple_return: number
  turnover: number
  cost_paid: number
  regime?: string | null
  top_symbol?: string | null
}

interface TimeseriesPayload {
  tracks: Record<TrackKey, Record<string, SeriesPoint[]>>
}

interface NavItem {
  key: ViewKey
  label: string
}

const STARTER_BALANCE = 10_000
const CHART_WIDTH = 1120
const CHART_HEIGHT = 420
const CHART_PADDING_X = 42
const CHART_PADDING_Y = 26
const REPO_URL = 'https://github.com/ErwinHe7/algorithmic-quant-trading'
const PAGES_SETTINGS_URL = `${REPO_URL}/settings/pages`

const NAV_ITEMS: NavItem[] = [
  { key: 'leaderboard', label: 'Leaderboard' },
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'artifacts', label: 'Artifacts' },
  { key: 'tasks', label: 'Work Tasks' },
  { key: 'learning', label: 'Learning' },
]

const TRACK_TITLES: Record<TrackKey, { label: string; detail: string }> = {
  proposal_core: {
    label: 'Core Benchmark',
    detail: 'Advanced Algorithms benchmark track',
  },
  ml_extension: {
    label: 'ML Extension',
    detail: 'Industry-style alpha + optimizer track',
  },
}

const STRATEGY_NOTES: Record<string, string> = {
  bcrp: 'Offline oracle benchmark used to bound regret against the best fixed rebalance in hindsight.',
  equal_weight: 'Sanity-check baseline that keeps the whole stack honest before we trust anything adaptive.',
  eg: 'First-order online learner that updates through multiplicative weights on the simplex.',
  ons: 'Second-order online learner that adapts with curvature and often wins when the market mix shifts.',
  universal_portfolio:
    'Sampled Cover-style portfolio that approximates the best constant rebalance without peeking at the future.',
  momentum: 'Trend-following heuristic that rotates into recent winners and pays for that conviction with turnover.',
  mean_reversion:
    'Counter-trend heuristic that leans into recent laggards and currently leads this benchmark slice.',
  ridge_alpha:
    'Transparent statistical alpha baseline using rolling ridge regression over handcrafted cross-sectional features.',
  attention_alpha:
    'Lightweight transformer-style forecaster that scores recent sequences before deterministic allocation.',
  blend_alpha:
    'Portfolio that blends statistical and attention signals, then sends them through the same optimizer.',
}

const STRATEGY_COLORS: Record<string, string> = {
  bcrp: '#ffb04c',
  equal_weight: '#79d4ff',
  eg: '#38bdf8',
  ons: '#9b8cff',
  universal_portfolio: '#7dd3fc',
  momentum: '#f97316',
  mean_reversion: '#65f0b6',
  ridge_alpha: '#7ee787',
  attention_alpha: '#b794f6',
  blend_alpha: '#ffd54f',
}

function formatPercent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value)
}

function formatCompactCurrency(value: number): string {
  const absolute = Math.abs(value)
  if (absolute >= 1000) {
    return `$${(value / 1000).toFixed(1)}k`
  }
  return formatCurrency(value)
}

function formatShortDate(value: string): string {
  return new Date(value).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function metricValue(metrics: StrategyMetrics, key: string): number {
  const value = metrics[key as keyof StrategyMetrics]
  return typeof value === 'number' ? value : 0
}

function orderStrategies(track: TrackSnapshot): StrategySnapshot[] {
  return Object.values(track.strategies).sort(
    (left, right) =>
      metricValue(right.metrics, track.primary_metric) - metricValue(left.metrics, track.primary_metric),
  )
}

function latestBalance(strategy: StrategySnapshot, points: SeriesPoint[] | undefined): number {
  const lastPoint = points?.at(-1)
  return (lastPoint?.equity ?? strategy.metrics.final_wealth) * STARTER_BALANCE
}

function clampIndex(index: number, size: number): number {
  if (size <= 0) {
    return 0
  }
  return Math.max(0, Math.min(size - 1, index))
}

function statusLabel(metrics: StrategyMetrics): string {
  if (metrics.sharpe >= 0.95 && metrics.max_drawdown <= 0.3) {
    return 'Thriving'
  }
  if (metrics.sharpe >= 0.7) {
    return 'Stable'
  }
  return 'Watch'
}

function pointEquity(point: SeriesPoint): number {
  return point.equity * STARTER_BALANCE
}

function estimatedTradeCount(points: SeriesPoint[] | undefined): number {
  if (!points?.length) {
    return 0
  }
  return points.filter((point) => point.turnover > 0.0001).length
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3.25" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 0 1-2.82 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.55V21a2 2 0 0 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.57 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.82l.06-.06A1.7 1.7 0 0 0 4.64 15a1.7 1.7 0 0 0-1.55-1.03H3a2 2 0 0 1 0-4h.09A1.7 1.7 0 0 0 4.64 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.82-2.83l.06.06A1.7 1.7 0 0 0 9 4.64a1.7 1.7 0 0 0 1.03-1.55V3a2 2 0 0 1 4 0v.09A1.7 1.7 0 0 0 15.1 4.64a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 0 1 2.83 2.82l-.06.06A1.7 1.7 0 0 0 19.36 9c.16.4.24.83.24 1.26s-.08.86-.2 1.26Z" />
    </svg>
  )
}

function SidebarIcon({ kind }: { kind: ViewKey }) {
  if (kind === 'leaderboard') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 21h8" />
        <path d="M12 17v4" />
        <path d="M7 4h10v3a5 5 0 0 1-10 0V4Z" />
        <path d="M7 6H4a2 2 0 0 0 2 2" />
        <path d="M17 6h3a2 2 0 0 1-2 2" />
      </svg>
    )
  }

  if (kind === 'dashboard') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 12a9 9 0 1 1 18 0" />
        <path d="M12 12l4-4" />
        <path d="M12 21a3 3 0 0 1-3-3h6a3 3 0 0 1-3 3Z" />
      </svg>
    )
  }

  if (kind === 'artifacts') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
        <path d="M14 3v5h5" />
        <path d="M9 13h6" />
        <path d="M9 17h4" />
      </svg>
    )
  }

  if (kind === 'tasks') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M8 3v4" />
        <path d="M16 3v4" />
        <path d="M3 10h18" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3a3 3 0 0 0-3 3c0 1 .4 1.93 1.05 2.61C7.12 9.62 5 12.13 5 15.14 5 18.38 8.13 21 12 21s7-2.62 7-5.86c0-3.01-2.12-5.52-5.05-6.53A3.74 3.74 0 0 0 15 6a3 3 0 0 0-3-3Z" />
      <path d="M9 15c.8.67 1.8 1 3 1s2.2-.33 3-1" />
    </svg>
  )
}

function buildLine(points: SeriesPoint[], minValue: number, maxValue: number): string {
  if (!points.length) {
    return ''
  }

  const usableWidth = CHART_WIDTH - CHART_PADDING_X * 2
  const usableHeight = CHART_HEIGHT - CHART_PADDING_Y * 2
  const span = Math.max(maxValue - minValue, 1)

  return points
    .map((point, index) => {
      const x =
        CHART_PADDING_X +
        (points.length === 1 ? usableWidth : (index / (points.length - 1)) * usableWidth)
      const y =
        CHART_HEIGHT -
        CHART_PADDING_Y -
        ((pointEquity(point) - minValue) / span) * usableHeight
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
}

interface BalanceChartProps {
  strategies: StrategySnapshot[]
  seriesMap: Record<string, SeriesPoint[]>
  focusKey: string
  onFocus: (key: string) => void
  emptyMessage?: string
}

function BalanceChart({ strategies, seriesMap, focusKey, onFocus, emptyMessage }: BalanceChartProps) {
  const chartStrategies = strategies
    .map((strategy) => ({
      strategy,
      points: seriesMap[strategy.definition.key] ?? [],
      color: STRATEGY_COLORS[strategy.definition.key] ?? '#7dd3fc',
    }))
    .filter((entry) => entry.points.length > 0)

  const maxLength = chartStrategies.reduce((max, entry) => Math.max(max, entry.points.length), 0)
  const [hoverIndex, setHoverIndex] = useState(maxLength > 0 ? maxLength - 1 : 0)
  const [hoveredKey, setHoveredKey] = useState('')

  if (!chartStrategies.length) {
    return <div className="chart-empty">{emptyMessage ?? 'No balance history available.'}</div>
  }

  const allValues = chartStrategies.flatMap((entry) => entry.points.map(pointEquity))
  const minValue = Math.min(...allValues)
  const maxValue = Math.max(...allValues)
  const activeIndex = clampIndex(hoverIndex, maxLength)
  const referencePoints = chartStrategies[0]?.points ?? []
  const activeDate = referencePoints[activeIndex]?.date ?? referencePoints.at(-1)?.date
  const activeKey = hoveredKey || focusKey || chartStrategies[0]?.strategy.definition.key
  const usableWidth = CHART_WIDTH - CHART_PADDING_X * 2
  const usableHeight = CHART_HEIGHT - CHART_PADDING_Y * 2
  const crosshairX =
    CHART_PADDING_X + (maxLength <= 1 ? usableWidth : (activeIndex / (maxLength - 1)) * usableWidth)
  const tooltipRows = chartStrategies
    .map((entry) => {
      const point = entry.points[clampIndex(activeIndex, entry.points.length)]
      return {
        key: entry.strategy.definition.key,
        name: entry.strategy.definition.name,
        value: point ? pointEquity(point) : latestBalance(entry.strategy, entry.points),
        color: entry.color,
      }
    })
    .sort((left, right) => {
      if (left.key === activeKey) {
        return -1
      }
      if (right.key === activeKey) {
        return 1
      }
      return right.value - left.value
    })

  const yTicks = Array.from({ length: 4 }, (_, index) => {
    const ratio = index / 3
    const value = maxValue - (maxValue - minValue) * ratio
    const y = CHART_PADDING_Y + ratio * usableHeight
    return { value, y }
  })

  const xTicks = Array.from({ length: 6 }, (_, index) => {
    const ratio = index / 5
    const pointIndex = clampIndex(Math.round(ratio * (referencePoints.length - 1)), referencePoints.length)
    const x = CHART_PADDING_X + ratio * usableWidth
    return {
      key: `${index}-${pointIndex}`,
      x,
      label: referencePoints[pointIndex]?.date ? formatShortDate(referencePoints[pointIndex].date) : '',
    }
  })

  return (
    <div className="chart-stack">
      <div
        className="chart-frame"
        onMouseLeave={() => {
          setHoverIndex(maxLength - 1)
          setHoveredKey('')
        }}
        onMouseMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect()
          const ratio = bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 1
          setHoverIndex(clampIndex(Math.round(ratio * (maxLength - 1)), maxLength))
        }}
      >
        <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="chart-svg" preserveAspectRatio="none">
          {yTicks.map((tick) => (
            <g key={tick.y}>
              <line x1={CHART_PADDING_X} y1={tick.y} x2={CHART_WIDTH - CHART_PADDING_X} y2={tick.y} />
              <text x={14} y={tick.y + 4} className="axis-label">
                {formatCurrency(tick.value)}
              </text>
            </g>
          ))}
          {xTicks.map((tick) => (
            <text key={tick.key} x={tick.x} y={CHART_HEIGHT - 4} textAnchor="middle" className="axis-label">
              {tick.label}
            </text>
          ))}
          {chartStrategies.map((entry) => {
            const isFocus = entry.strategy.definition.key === activeKey
            const activePoint = entry.points[clampIndex(activeIndex, entry.points.length)]
            const span = Math.max(maxValue - minValue, 1)
            const activeY =
              activePoint === undefined
                ? CHART_HEIGHT / 2
                : CHART_HEIGHT -
                  CHART_PADDING_Y -
                  ((pointEquity(activePoint) - minValue) / span) * (CHART_HEIGHT - CHART_PADDING_Y * 2)
            const lastPoint = entry.points.at(-1)
            const lastX = CHART_WIDTH - CHART_PADDING_X
            const lastY =
              lastPoint === undefined
                ? CHART_HEIGHT / 2
                : CHART_HEIGHT -
                  CHART_PADDING_Y -
                  ((pointEquity(lastPoint) - minValue) / span) * (CHART_HEIGHT - CHART_PADDING_Y * 2)

            return (
              <g key={entry.strategy.definition.key}>
                <path
                  d={buildLine(entry.points, minValue, maxValue)}
                  stroke="transparent"
                  strokeWidth={16}
                  fill="none"
                  className="chart-hit"
                  onMouseEnter={() => {
                    setHoveredKey(entry.strategy.definition.key)
                    onFocus(entry.strategy.definition.key)
                  }}
                />
                <path
                  d={buildLine(entry.points, minValue, maxValue)}
                  stroke={entry.color}
                  strokeOpacity={isFocus ? 1 : 0.58}
                  strokeWidth={isFocus ? 3.8 : 2.2}
                  fill="none"
                  className="chart-line"
                  onMouseEnter={() => {
                    setHoveredKey(entry.strategy.definition.key)
                    onFocus(entry.strategy.definition.key)
                  }}
                />
                <circle cx={crosshairX} cy={activeY} r={isFocus ? 5 : 3.1} fill={entry.color} />
                <circle cx={lastX} cy={lastY} r={isFocus ? 4.5 : 3} fill={entry.color} opacity={0.95} />
              </g>
            )
          })}
          <line
            className="crosshair"
            x1={crosshairX}
            y1={CHART_PADDING_Y}
            x2={crosshairX}
            y2={CHART_HEIGHT - CHART_PADDING_Y}
          />
        </svg>
        <div className="chart-tooltip">
          <span>{activeDate ? formatShortDate(activeDate) : 'Latest checkpoint'}</span>
          {tooltipRows.map((row) => (
            <div key={row.key} className={row.key === activeKey ? 'active' : ''}>
              <i style={{ background: row.color }} />
              <strong>{row.name}</strong>
              <em>{formatCurrency(row.value)}</em>
            </div>
          ))}
        </div>
      </div>
      <div className="chart-legend">
        {chartStrategies.map((entry) => (
          <button
            key={entry.strategy.definition.key}
            type="button"
            className={entry.strategy.definition.key === activeKey ? 'active' : ''}
            onMouseEnter={() => {
              setHoveredKey(entry.strategy.definition.key)
              onFocus(entry.strategy.definition.key)
            }}
            onMouseLeave={() => setHoveredKey('')}
            onClick={() => onFocus(entry.strategy.definition.key)}
          >
            <i style={{ background: entry.color }} />
            <span>{entry.strategy.definition.name}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

interface LeaderboardViewProps {
  track: TrackSnapshot
  strategies: StrategySnapshot[]
  seriesMap: Record<string, SeriesPoint[]>
  focusKey: string
  onFocus: (key: string) => void
  dataSummary: ProjectSnapshot['data_summary']
  emptyMessage?: string
}

function LeaderboardView({
  track,
  strategies,
  seriesMap,
  focusKey,
  onFocus,
  dataSummary,
  emptyMessage,
}: LeaderboardViewProps) {
  const leader = strategies[0]
  const leaderBalance = leader ? latestBalance(leader, seriesMap[leader.definition.key]) : 0
  const dataPoints = Math.max(...Object.values(seriesMap).map((points) => points.length), 0)
  const years = Math.max(dataSummary.rows / 252, 1)

  return (
    <div className="view-stack">
      <section className="hero-banner">
        <div>
          <div className="hero-eyebrow">
            <span>Leaderboard</span>
            <strong>LIVE</strong>
          </div>
          <h1>{track.track_name}</h1>
          <p>
            {strategies.length} strategies competing over {dataSummary.rows} trading days, updated through{' '}
            {formatShortDate(dataSummary.end)}.
          </p>
        </div>
        <div className="hero-performer">
          <span>Top Performer</span>
          <strong>{leader?.definition.name ?? 'Pending run'}</strong>
          <em>{formatCurrency(leaderBalance)}</em>
        </div>
      </section>

      <section className="ticker-strip">
        {strategies.map((strategy) => (
          <button
            key={strategy.definition.key}
            type="button"
            className={`ticker-pill ${focusKey === strategy.definition.key ? 'active' : ''}`}
            onClick={() => onFocus(strategy.definition.key)}
          >
            <i style={{ background: STRATEGY_COLORS[strategy.definition.key] ?? '#7dd3fc' }} />
            <span>{strategy.definition.name}</span>
            <strong>{formatCurrency(latestBalance(strategy, seriesMap[strategy.definition.key]))}</strong>
          </button>
        ))}
      </section>

      <section className="panel chart-panel">
        <div className="panel-head">
          <div>
            <div className="panel-title-row">
              <h2>Balance History</h2>
              <span className="live-pill">LIVE</span>
            </div>
            <p>Walk-forward equity curves with the same cost model applied to every strategy.</p>
          </div>
          <div className="panel-head-meta">
            <span>{dataPoints} data points</span>
            <div className="panel-chip">Daily bars</div>
          </div>
        </div>
        <BalanceChart
          strategies={strategies}
          seriesMap={seriesMap}
          focusKey={focusKey}
          onFocus={onFocus}
          emptyMessage={emptyMessage}
        />
      </section>

      <section className="panel rankings-panel">
        <div className="panel-head">
          <div>
            <h2>Ranking Table</h2>
            <p>Starter capital is normalized to {formatCurrency(STARTER_BALANCE)} for side-by-side comparison.</p>
          </div>
        </div>
        <div className="table-scroll">
          <table className="ranking-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Strategy</th>
                <th>Starter</th>
                <th>Balance</th>
                <th>% Change</th>
                <th>Income</th>
                <th>Cost</th>
                <th>Run Rate</th>
                <th>Avg Quality</th>
                <th>Tasks</th>
                <th>Turnover</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((strategy, index) => {
                const balance = latestBalance(strategy, seriesMap[strategy.definition.key])
                const income = balance - STARTER_BALANCE
                const cost = strategy.metrics.cost_drag * STARTER_BALANCE
                const annualRunRate = income / years
                const dailyRunRate = annualRunRate / 252
                const taskCount = estimatedTradeCount(seriesMap[strategy.definition.key])

                return (
                  <tr
                    key={strategy.definition.key}
                    className={focusKey === strategy.definition.key ? 'is-focus' : ''}
                    onMouseEnter={() => onFocus(strategy.definition.key)}
                  >
                    <td>#{index + 1}</td>
                    <td>
                      <div className="table-name">
                        <i style={{ background: STRATEGY_COLORS[strategy.definition.key] ?? '#7dd3fc' }} />
                        <div>
                          <strong>{strategy.definition.name}</strong>
                          <span>{strategy.definition.family}</span>
                        </div>
                      </div>
                    </td>
                    <td>{formatCurrency(STARTER_BALANCE)}</td>
                    <td>{formatCurrency(balance)}</td>
                    <td className={income >= 0 ? 'metric-up' : 'metric-down'}>
                      {income >= 0 ? '+' : ''}
                      {formatPercent(balance / STARTER_BALANCE - 1)}
                    </td>
                    <td className="metric-up">{formatCurrency(income)}</td>
                    <td className="metric-down">{formatCurrency(cost)}</td>
                    <td className="pay-rate">
                      {formatCompactCurrency(annualRunRate)}
                      <span>{formatCompactCurrency(dailyRunRate)}/day</span>
                    </td>
                    <td>{formatPercent(strategy.metrics.hit_rate, 1)}</td>
                    <td>{taskCount}</td>
                    <td>{formatPercent(strategy.metrics.avg_turnover)}</td>
                    <td>
                      <span className={`status-pill ${statusLabel(strategy.metrics).toLowerCase()}`}>
                        {statusLabel(strategy.metrics)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

interface DashboardViewProps {
  track: TrackSnapshot
  strategies: StrategySnapshot[]
  seriesMap: Record<string, SeriesPoint[]>
  focus: StrategySnapshot
  focusSeries: SeriesPoint[]
  dataSummary: ProjectSnapshot['data_summary']
}

function DashboardView({
  track,
  strategies,
  seriesMap,
  focus,
  focusSeries,
  dataSummary,
}: DashboardViewProps) {
  const leader = strategies[0]
  const averageSharpe =
    strategies.reduce((sum, strategy) => sum + strategy.metrics.sharpe, 0) / Math.max(strategies.length, 1)
  const weights = Object.entries(focus.latest_weights).sort((left, right) => right[1] - left[1])

  return (
    <div className="view-stack">
      <section className="metric-strip">
        <article className="stat-card">
          <span>Leader</span>
          <strong>{leader.definition.name}</strong>
          <em>{formatPercent(metricValue(leader.metrics, track.primary_metric))}</em>
        </article>
        <article className="stat-card">
          <span>Benchmark</span>
          <strong>{track.benchmark ? track.strategies[track.benchmark]?.definition.name ?? track.benchmark : 'None'}</strong>
          <em>{track.regime_method ? 'with regime labels' : 'extension track'}</em>
        </article>
        <article className="stat-card">
          <span>Average Sharpe</span>
          <strong>{averageSharpe.toFixed(2)}</strong>
          <em>{formatShortDate(dataSummary.start)} to {formatShortDate(dataSummary.end)}</em>
        </article>
        <article className="stat-card">
          <span>Transaction Cost</span>
          <strong>{String(track.track_key === 'proposal_core' ? 'Shared model' : 'Optimizer aware')}</strong>
          <em>{String(seriesMap[focus.definition.key]?.length ?? 0)} walk-forward points</em>
        </article>
      </section>

      <section className="dashboard-grid">
        <article className="panel focus-panel">
          <div className="panel-head">
            <div>
              <h2>{focus.definition.name}</h2>
              <p>{focus.definition.description}</p>
            </div>
            <div className="panel-chip">{focus.definition.family}</div>
          </div>
          <div className="focus-metrics">
            <div>
              <span>Annualized Return</span>
              <strong>{formatPercent(focus.metrics.annualized_return)}</strong>
            </div>
            <div>
              <span>Sharpe</span>
              <strong>{focus.metrics.sharpe.toFixed(2)}</strong>
            </div>
            <div>
              <span>Max Drawdown</span>
              <strong>{formatPercent(focus.metrics.max_drawdown)}</strong>
            </div>
            <div>
              <span>Turnover</span>
              <strong>{formatPercent(focus.metrics.avg_turnover)}</strong>
            </div>
          </div>
          <p className="focus-note">{STRATEGY_NOTES[focus.definition.key] ?? focus.definition.theory}</p>
          <div className="mini-curve">
            <BalanceChart
              strategies={[focus]}
              seriesMap={{ [focus.definition.key]: focusSeries }}
              focusKey={focus.definition.key}
              onFocus={() => undefined}
            />
          </div>
        </article>

        <article className="panel exposure-panel">
          <div className="panel-head">
            <div>
              <h2>Latest Weights</h2>
              <p>Current allocation snapshot from the latest walk-forward decision.</p>
            </div>
          </div>
          <div className="weight-stack">
            {weights.map(([symbol, value]) => (
              <div key={symbol} className="weight-row">
                <span>{symbol}</span>
                <div className="weight-bar">
                  <i style={{ width: `${value * 100}%` }} />
                </div>
                <strong>{formatPercent(value)}</strong>
              </div>
            ))}
          </div>
        </article>

        <article className="panel theory-panel">
          <div className="panel-head">
            <div>
              <h2>Track Logic</h2>
              <p>{TRACK_TITLES[track.track_key].detail}</p>
            </div>
          </div>
          <div className="theory-list">
            <div>
              <span>Primary Metric</span>
              <strong>{track.primary_metric.replaceAll('_', ' ')}</strong>
            </div>
            <div>
              <span>Regime Method</span>
              <strong>{track.regime_method ?? 'Not applied in this track'}</strong>
            </div>
            <div>
              <span>Universe</span>
              <strong>{dataSummary.symbols.join(', ')}</strong>
            </div>
            <div>
              <span>Benchmark</span>
              <strong>{track.benchmark ?? 'None'}</strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  )
}

interface SimpleProps {
  snapshot: ProjectSnapshot
  track: TrackSnapshot
  strategies: StrategySnapshot[]
}

function ArtifactsView({ snapshot, track, strategies }: SimpleProps) {
  const leader = strategies[0]

  return (
    <div className="view-stack">
      <section className="panel artifact-grid">
        <article className="artifact-card">
          <span>Public Snapshot</span>
          <strong>public/project-snapshot.json</strong>
          <p>Frontend summary payload with strategy metrics, architecture, and latest weights.</p>
        </article>
        <article className="artifact-card">
          <span>Timeseries</span>
          <strong>public/project-timeseries.json</strong>
          <p>Daily walk-forward equity history used by the leaderboard chart and detail panels.</p>
        </article>
        <article className="artifact-card">
          <span>Research Report</span>
          <strong>artifacts/research/research_report.md</strong>
          <p>Human-readable summary for GitHub, reviewers, and handoff discussions.</p>
        </article>
        <article className="artifact-card">
          <span>Metrics CSV</span>
          <strong>{`artifacts/research/${track.track_key}_metrics.csv`}</strong>
          <p>Sortable metrics for the active track, including turnover and cost drag diagnostics.</p>
        </article>
      </section>

      <section className="panel command-panel">
        <div className="panel-head">
          <div>
            <h2>Runbook</h2>
            <p>Use this flow when you want the GitHub homepage and artifacts to stay in sync.</p>
          </div>
        </div>
        <pre>{`python -m pip install -r requirements-research.txt
npm install
npm run research:run
npm run build
npm run lint`}</pre>
        <div className="artifact-notes">
          <div>
            <span>Current track leader</span>
            <strong>{leader.definition.name}</strong>
          </div>
          <div>
            <span>Sample window</span>
            <strong>{formatShortDate(snapshot.data_summary.start)} to {formatShortDate(snapshot.data_summary.end)}</strong>
          </div>
          <div>
            <span>Rows</span>
            <strong>{snapshot.data_summary.rows}</strong>
          </div>
        </div>
      </section>
    </div>
  )
}

function TasksView({ snapshot }: { snapshot: ProjectSnapshot }) {
  return (
    <div className="view-stack">
      <section className="task-grid">
        {snapshot.architecture.agent_roles.map((role) => (
          <article key={role.id} className="panel task-card">
            <span>{role.id}</span>
            <h2>{role.title}</h2>
            <p>{role.purpose}</p>
          </article>
        ))}
      </section>

      <section className="panel checklist-panel">
        <div className="panel-head">
          <div>
            <h2>Recommended Queue</h2>
            <p>These are the next implementation steps that still keep the live path deterministic.</p>
          </div>
        </div>
        <div className="checklist">
          {snapshot.recommended_path.map((item) => (
            <div key={item} className="check-row">
              <i />
              <span>{item}</span>
            </div>
          ))}
          <div className="check-row">
            <i />
            <span>Wire a paper-trading adapter only after the research outputs are stable and versioned.</span>
          </div>
          <div className="check-row">
            <i />
            <span>Keep order generation deterministic even if the research layer becomes more agentic.</span>
          </div>
        </div>
      </section>
    </div>
  )
}

function LearningView({ strategies }: { strategies: StrategySnapshot[] }) {
  return (
    <div className="strategy-grid">
      {strategies.map((strategy) => (
        <article key={strategy.definition.key} className="panel strategy-card">
          <div className="strategy-top">
            <div>
              <span>{strategy.definition.family}</span>
              <h2>{strategy.definition.name}</h2>
            </div>
            <div className="strategy-dot" style={{ background: STRATEGY_COLORS[strategy.definition.key] ?? '#7dd3fc' }} />
          </div>
          <p>{STRATEGY_NOTES[strategy.definition.key] ?? strategy.definition.description}</p>
          <div className="learning-metrics">
            <div>
              <span>Complexity</span>
              <strong>{strategy.definition.complexity}</strong>
            </div>
            <div>
              <span>Theory</span>
              <strong>{strategy.definition.theory}</strong>
            </div>
            <div>
              <span>Hit Rate</span>
              <strong>{formatPercent(strategy.metrics.hit_rate)}</strong>
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null)
  const [timeseries, setTimeseries] = useState<TimeseriesPayload | null>(null)
  const [timeseriesError, setTimeseriesError] = useState('')
  const [view, setView] = useState<ViewKey>('leaderboard')
  const [trackKey, setTrackKey] = useState<TrackKey>('proposal_core')
  const [focusKey, setFocusKey] = useState('')

  useEffect(() => {
    let disposed = false

    async function loadData() {
      const snapshotResponse = await fetch('./project-snapshot.json')
      const nextSnapshot = (await snapshotResponse.json()) as ProjectSnapshot

      if (!disposed) {
        setSnapshot(nextSnapshot)
      }

      try {
        const timeseriesResponse = await fetch('./project-timeseries.json')
        if (!timeseriesResponse.ok) {
          throw new Error(`HTTP ${timeseriesResponse.status}`)
        }

        const nextTimeseries = (await timeseriesResponse.json()) as TimeseriesPayload
        if (!disposed) {
          setTimeseries(nextTimeseries)
          setTimeseriesError('')
        }
      } catch (error) {
        if (!disposed) {
          setTimeseries(null)
          setTimeseriesError(error instanceof Error ? error.message : 'Failed to load timeseries data')
        }
      }
    }

    void loadData()

    return () => {
      disposed = true
    }
  }, [])

  if (!snapshot) {
    return (
      <main className="console-shell loading-shell">
        <section className="loading-card">
          <span>QuantBench</span>
          <h1>Loading research snapshot</h1>
          <p>If this stalls, regenerate the public data with <code>npm run research:run</code>.</p>
        </section>
      </main>
    )
  }

  const track = snapshot.tracks[trackKey]
  const strategies = orderStrategies(track)
  const trackSeries = timeseries?.tracks[trackKey] ?? {}
  const activeFocusKey = track.strategies[focusKey] ? focusKey : (strategies[0]?.definition.key ?? '')
  const focus = track.strategies[activeFocusKey] ?? strategies[0]
  const focusSeries = trackSeries[focus.definition.key] ?? []
  const chartEmptyMessage = timeseriesError
    ? `Balance history failed to load: ${timeseriesError}`
    : 'Balance history is still loading or the timeseries payload is unavailable.'

  return (
    <main className="console-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <div className="brand-mark">Q</div>
          <div>
            <strong>QuantBench</strong>
            <span>Quant Trading Arena</span>
          </div>
        </div>

        <div className="sidebar-status">
          <div className="sidebar-status-label">
            <i />
            <span>GitHub Pages</span>
          </div>
          <a
            className="sidebar-settings"
            href={PAGES_SETTINGS_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Open GitHub Pages settings"
            title="Open GitHub Pages settings"
          >
            <SettingsIcon />
          </a>
        </div>

        <div className="track-switch">
          {(Object.keys(TRACK_TITLES) as TrackKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className={trackKey === key ? 'active' : ''}
              onClick={() => setTrackKey(key)}
            >
              <strong>{TRACK_TITLES[key].label}</strong>
              <span>{TRACK_TITLES[key].detail}</span>
            </button>
          ))}
        </div>

        <nav className="nav-stack">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={view === item.key ? 'active' : ''}
              onClick={() => setView(item.key)}
            >
              <span className="nav-icon">
                <SidebarIcon kind={item.key} />
              </span>
              <span className="nav-label">{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="strategy-list">
          <span className="sidebar-label">Strategies ({strategies.length})</span>
          {strategies.map((strategy) => (
            <button
              key={strategy.definition.key}
              type="button"
              className={`strategy-list-item ${activeFocusKey === strategy.definition.key ? 'active' : ''}`}
              onClick={() => setFocusKey(strategy.definition.key)}
            >
              <i style={{ background: STRATEGY_COLORS[strategy.definition.key] ?? '#7dd3fc' }} />
              <div>
                <strong>{strategy.definition.name}</strong>
                <span>{formatCurrency(latestBalance(strategy, trackSeries[strategy.definition.key]))}</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <section className="workspace">
        {view !== 'leaderboard' && (
          <header className="workspace-header">
            <div>
              <span>{TRACK_TITLES[trackKey].detail}</span>
              <h1>{track.track_name}</h1>
            </div>
            <div className="workspace-meta">
              <div>
                <span>Data Range</span>
                <strong>{formatShortDate(snapshot.data_summary.start)} to {formatShortDate(snapshot.data_summary.end)}</strong>
              </div>
              <div>
                <span>Universe</span>
                <strong>{snapshot.data_summary.symbols.join(', ')}</strong>
              </div>
              <div>
                <span>Primary Metric</span>
                <strong>{track.primary_metric.replaceAll('_', ' ')}</strong>
              </div>
            </div>
          </header>
        )}

        {view === 'leaderboard' && (
          <LeaderboardView
            track={track}
            strategies={strategies}
            seriesMap={trackSeries}
            focusKey={activeFocusKey}
            onFocus={setFocusKey}
            dataSummary={snapshot.data_summary}
            emptyMessage={chartEmptyMessage}
          />
        )}
        {view === 'dashboard' && (
          <DashboardView
            track={track}
            strategies={strategies}
            seriesMap={trackSeries}
            focus={focus}
            focusSeries={focusSeries}
            dataSummary={snapshot.data_summary}
          />
        )}
        {view === 'artifacts' && <ArtifactsView snapshot={snapshot} track={track} strategies={strategies} />}
        {view === 'tasks' && <TasksView snapshot={snapshot} />}
        {view === 'learning' && <LearningView strategies={strategies} />}
      </section>
    </main>
  )
}
