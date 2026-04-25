import { assetIds, marketTape, tradingFriction, warmupPeriods } from '../data/demoData'
import type {
  AssetId,
  HindsightSummary,
  SimulationResult,
  StrategyDefinition,
  StrategyId,
  StrategyMetrics,
} from '../types'

type Selection = {
  asset: AssetId
  reason: string
}

type StrategyRuntime = {
  pick: (index: number) => Selection
  update: (settlementIndex: number, asset: AssetId, realizedReturn: number) => void
}

const assetIndex: Record<AssetId, number> = {
  SPY: 0,
  QQQ: 1,
  GLD: 2,
  TLT: 3,
}

const sketchSeeds = [
  { a: 3, b: 1, s1: 5, s2: 1 },
  { a: 5, b: 2, s1: 7, s2: 1 },
  { a: 7, b: 3, s1: 9, s2: 1 },
]

const hyperplanes = [
  [1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1, 1, -1],
  [1, 1, -1, -1, 1, 1, -1, -1, 1, 1, -1, -1, 1, 1, -1, -1],
  [1, -1, -1, 1, 1, -1, -1, 1, 1, -1, -1, 1, 1, -1, -1, 1],
  [1, 1, 1, 1, -1, -1, -1, -1, 1, 1, 1, 1, -1, -1, -1, -1],
  [1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, -1, -1, 1, -1, 1],
  [-1, 1, 1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, -1, -1, 1],
]

function cumulativeTrailingReturn(asset: AssetId, currentIndex: number, lookback: number) {
  let equity = 1
  const start = Math.max(1, currentIndex - lookback + 1)

  for (let cursor = start; cursor <= currentIndex; cursor += 1) {
    equity *= 1 + marketTape[cursor].returns[asset]
  }

  return equity - 1
}

function recentReturns(asset: AssetId, currentIndex: number, lookback: number) {
  const start = Math.max(1, currentIndex - lookback + 1)
  const values: number[] = []

  for (let cursor = start; cursor <= currentIndex; cursor += 1) {
    values.push(marketTape[cursor].returns[asset])
  }

  return values
}

function average(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function stdev(values: number[]) {
  if (values.length < 2) {
    return 0
  }

  const mean = average(values)
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1)

  return Math.sqrt(variance)
}

function correlation(left: number[], right: number[]) {
  if (left.length !== right.length || left.length < 2) {
    return 0
  }

  const leftMean = average(left)
  const rightMean = average(right)
  let numerator = 0
  let leftVar = 0
  let rightVar = 0

  for (let index = 0; index < left.length; index += 1) {
    const l = left[index] - leftMean
    const r = right[index] - rightMean
    numerator += l * r
    leftVar += l * l
    rightVar += r * r
  }

  const denominator = Math.sqrt(leftVar * rightVar)
  return denominator === 0 ? 0 : numerator / denominator
}

function maxDrawdown(curve: number[]) {
  let peak = curve[0]
  let worst = 0

  for (const value of curve) {
    peak = Math.max(peak, value)
    worst = Math.min(worst, value / peak - 1)
  }

  return Math.abs(worst)
}

function trailingWinner(currentIndex: number, lookback = 3) {
  return assetIds
    .map((asset) => ({
      asset,
      score: cumulativeTrailingReturn(asset, currentIndex, lookback),
    }))
    .sort((left, right) => right.score - left.score)[0]
}

function bestNextAsset(settlementIndex: number) {
  return assetIds
    .map((asset) => ({
      asset,
      score: marketTape[settlementIndex].returns[asset],
    }))
    .sort((left, right) => right.score - left.score)[0].asset
}

function flattenWindow(currentIndex: number, lookback = 4) {
  const vector: number[] = []
  const start = currentIndex - lookback + 1

  for (let cursor = start; cursor <= currentIndex; cursor += 1) {
    for (const asset of assetIds) {
      vector.push(marketTape[cursor].returns[asset])
    }
  }

  return vector
}

function squaredDistance(left: number[], right: number[]) {
  let sum = 0

  for (let index = 0; index < left.length; index += 1) {
    sum += (left[index] - right[index]) ** 2
  }

  return sum
}

function signatureFromWindow(vector: number[]) {
  return hyperplanes
    .map((plane) => {
      let dot = 0
      for (let index = 0; index < vector.length; index += 1) {
        dot += vector[index] * plane[index]
      }
      return dot >= 0 ? '1' : '0'
    })
    .join('')
}

function createBuyHold(): StrategyRuntime {
  return {
    pick: () => ({
      asset: 'SPY',
      reason: 'Baseline control: hold SPY through the full replay.',
    }),
    update: () => undefined,
  }
}

function createCountSketchFlow(): StrategyRuntime {
  const width = 17
  const counters = sketchSeeds.map(() => Array(width).fill(0))
  let observations = 0

  function bucket(asset: AssetId, row: number) {
    const seed = sketchSeeds[row]
    return (seed.a * assetIndex[asset] + seed.b) % width
  }

  function sign(asset: AssetId, row: number) {
    const seed = sketchSeeds[row]
    return ((seed.s1 * assetIndex[asset] + seed.s2) % 2) * 2 - 1
  }

  function estimate(asset: AssetId) {
    const rowEstimates = counters.map((_, row) => sign(asset, row) * counters[row][bucket(asset, row)])
    return rowEstimates.sort((left, right) => left - right)[1]
  }

  return {
    pick: (index) => {
      if (observations < 4) {
        const fallback = trailingWinner(index, 3)
        return {
          asset: fallback.asset,
          reason: `Warm start fallback: ${fallback.asset} leads the recent tape.`,
        }
      }

      const scored = assetIds.map((asset) => ({
        asset,
        score: estimate(asset) + cumulativeTrailingReturn(asset, index, 2) * 120,
      }))
      const best = scored.sort((left, right) => right.score - left.score)[0]

      return {
        asset: best.asset,
        reason: `CountSketch tracks the replay's heavy-hitter winners; ${best.asset} has the strongest sketch score.`,
      }
    },
    update: (settlementIndex) => {
      const winner = bestNextAsset(settlementIndex)
      const weight = 1 + Math.max(marketTape[settlementIndex].returns[winner], 0) * 120

      sketchSeeds.forEach((_, row) => {
        counters[row][bucket(winner, row)] += sign(winner, row) * weight
      })

      observations += 1
    },
  }
}

function createMwuPortfolio(): StrategyRuntime {
  const weights: Record<AssetId, number> = { SPY: 1, QQQ: 1, GLD: 1, TLT: 1 }
  const eta = 18

  return {
    pick: () => {
      const best = assetIds
        .map((asset) => ({ asset, score: weights[asset] }))
        .sort((left, right) => right.score - left.score)[0]

      return {
        asset: best.asset,
        reason: `MWU / Hedge keeps the largest weight on ${best.asset}.`,
      }
    },
    update: (settlementIndex) => {
      let total = 0

      for (const asset of assetIds) {
        weights[asset] *= Math.exp(eta * marketTape[settlementIndex].returns[asset])
        total += weights[asset]
      }

      for (const asset of assetIds) {
        weights[asset] /= total
      }
    },
  }
}

function createSpectralRotation(): StrategyRuntime {
  return {
    pick: (index) => {
      if (index < 8) {
        const fallback = trailingWinner(index, 4)
        return {
          asset: fallback.asset,
          reason: `Warm start fallback: ${fallback.asset} leads the short replay window.`,
        }
      }

      const lookback = 6
      const affinity = assetIds.map((left) =>
        assetIds.map((right) => {
          if (left === right) return 1
          return Math.max(correlation(recentReturns(left, index, lookback), recentReturns(right, index, lookback)), 0) + 0.05
        }),
      )

      let vector = [1, 1, 1, 1]
      for (let step = 0; step < 8; step += 1) {
        const next = affinity.map((row) => row.reduce((sum, value, column) => sum + value * vector[column], 0))
        const norm = Math.sqrt(next.reduce((sum, value) => sum + value * value, 0)) || 1
        vector = next.map((value) => value / norm)
      }

      const scored = assetIds.map((asset, idx) => {
        const momentum = cumulativeTrailingReturn(asset, index, 3)
        const risk = stdev(recentReturns(asset, index, lookback))
        return {
          asset,
          score: vector[idx] * 0.65 + momentum * 18 - risk * 8,
        }
      })
      const best = scored.sort((left, right) => right.score - left.score)[0]

      return {
        asset: best.asset,
        reason: `Spectral rotation scores central assets in the rolling correlation graph; ${best.asset} wins this regime.`,
      }
    },
    update: () => undefined,
  }
}

function createLshRegimeMatch(): StrategyRuntime {
  const memory: Array<{ window: number[]; signature: string; nextAsset: AssetId }> = []

  return {
    pick: (index) => {
      if (index < 7 || memory.length < 5) {
        const fallback = trailingWinner(index, 4)
        return {
          asset: fallback.asset,
          reason: `Warm start fallback: ${fallback.asset} leads the recent window.`,
        }
      }

      const window = flattenWindow(index, 4)
      const signature = signatureFromWindow(window)
      const sameBucket = memory.filter((item) => item.signature === signature)
      const candidates = sameBucket.length > 0 ? sameBucket : memory
      const nearest = candidates.sort(
        (left, right) =>
          squaredDistance(left.window, window) - squaredDistance(right.window, window),
      )[0]

      return {
        asset: nearest.nextAsset,
        reason: `LSH regime match found a similar past window and copied the next winning asset: ${nearest.nextAsset}.`,
      }
    },
    update: (settlementIndex) => {
      if (settlementIndex < 5) {
        return
      }

      memory.push({
        window: flattenWindow(settlementIndex - 1, 4),
        signature: signatureFromWindow(flattenWindow(settlementIndex - 1, 4)),
        nextAsset: bestNextAsset(settlementIndex),
      })

      if (memory.length > 64) {
        memory.shift()
      }
    },
  }
}

export const strategyDefinitions: StrategyDefinition[] = [
  {
    id: 'buy-hold',
    name: 'Buy & Hold',
    family: 'Baseline',
    description: 'Control strategy on the same replay tape.',
    complexity: 'O(1) per round',
    guarantee: 'Benchmark only.',
    thesis: 'Gives the comparison a passive floor.',
  },
  {
    id: 'ucb',
    name: 'MWU Portfolio',
    family: 'Optimization / Online',
    description: 'Multiplicative weights update over the 4-ETF action set.',
    complexity: 'O(K) per round',
    guarantee: 'Full-information online-learning family.',
    thesis: 'Directly tied to the course online algorithms thread.',
  },
  {
    id: 'momentum',
    name: 'CountSketch Flow',
    family: 'Streaming / Heavy Hitters',
    description: 'Approximate heavy-hitter tracking over replay winners.',
    complexity: 'O(1) update, O(K) query',
    guarantee: 'Streaming-inspired approximation.',
    thesis: 'Turns sketching / heavy hitters into a trading selector.',
  },
  {
    id: 'exp3',
    name: 'LSH Regime Match',
    family: 'Nearest Neighbor / LSH',
    description: 'Hash similar market windows and reuse the next-step winner.',
    complexity: 'O(KL) per round in this small demo',
    guarantee: 'Approximate retrieval framing.',
    thesis: 'Uses nearest-neighbor ideas on replay windows.',
  },
  {
    id: 'mean-reversion',
    name: 'Spectral Rotation',
    family: 'Spectral Graph',
    description: 'Rolling correlation graph with spectral centrality scoring.',
    complexity: 'O(K^2L) per round',
    guarantee: 'Spectral heuristic.',
    thesis: 'Makes the graph / Laplacian side of the class visible.',
  },
] as const

function createStrategyRuntime(id: StrategyId) {
  switch (id) {
    case 'buy-hold':
      return createBuyHold()
    case 'ucb':
      return createMwuPortfolio()
    case 'momentum':
      return createCountSketchFlow()
    case 'exp3':
      return createLshRegimeMatch()
    case 'mean-reversion':
      return createSpectralRotation()
  }
}

function computeHindsightSummary(): HindsightSummary {
  const scored = assetIds.map((asset) => {
    let equity = 1

    for (let index = warmupPeriods; index < marketTape.length - 1; index += 1) {
      equity *= 1 + marketTape[index + 1].returns[asset]
    }

    return { asset, equity }
  })

  const best = scored.sort((left, right) => right.equity - left.equity)[0]

  return {
    bestAsset: best.asset,
    finalValue: best.equity,
    netReturn: best.equity - 1,
  }
}

function buildMetrics(
  netReturns: number[],
  grossReturns: number[],
  equityCurve: number[],
  switches: number,
  hindsight: HindsightSummary,
): StrategyMetrics {
  const finalValue = equityCurve.at(-1) ?? 1
  const dailyStd = stdev(netReturns)
  const sharpe =
    dailyStd === 0 ? 0 : (average(netReturns) / dailyStd) * Math.sqrt(252)

  return {
    finalValue,
    netReturn: finalValue - 1,
    grossReturn: grossReturns.reduce((equity, value) => equity * (1 + value), 1) - 1,
    sharpe,
    maxDrawdown: maxDrawdown(equityCurve),
    turnover: switches / Math.max(netReturns.length, 1),
    winRate:
      netReturns.filter((value) => value > 0).length / Math.max(netReturns.length, 1),
    regretProxy: Math.max(hindsight.netReturn - (finalValue - 1), 0),
    minEquity: Math.min(...equityCurve),
  }
}

function runStrategy(definition: StrategyDefinition, hindsight: HindsightSummary): SimulationResult {
  const runtime = createStrategyRuntime(definition.id)
  const decisionLog: SimulationResult['decisionLog'] = []
  const netReturns: number[] = []
  const grossReturns: number[] = []
  const equityCurve = [1]
  let equity = 1
  let lastAsset: AssetId | null = null
  let switches = 0

  for (let index = warmupPeriods; index < marketTape.length - 1; index += 1) {
    const decisionPoint = marketTape[index]
    const nextPoint = marketTape[index + 1]
    const selection = runtime.pick(index)
    const switched = lastAsset !== null && lastAsset !== selection.asset
    const switchCost = switched ? tradingFriction : 0
    const grossReturn = nextPoint.returns[selection.asset]
    const realizedReturn = grossReturn - switchCost

    equity *= 1 + realizedReturn
    equityCurve.push(equity)
    grossReturns.push(grossReturn)
    netReturns.push(realizedReturn)
    switches += switched ? 1 : 0

    decisionLog.push({
      index: decisionLog.length,
      decisionDate: decisionPoint.date,
      executionDate: nextPoint.date,
      regime: decisionPoint.regime,
      note: decisionPoint.note,
      selectedAsset: selection.asset,
      reason: selection.reason,
      grossReturn,
      realizedReturn,
      switchCost,
      switched,
      equity,
    })

    runtime.update(index + 1, selection.asset, grossReturn)
    lastAsset = selection.asset
  }

  return {
    definition,
    metrics: buildMetrics(netReturns, grossReturns, equityCurve, switches, hindsight),
    decisionLog,
    equityCurve,
    timeline: marketTape.slice(warmupPeriods),
  }
}

export const hindsightSummary = computeHindsightSummary()

export const simulationResults = strategyDefinitions.map((definition) =>
  runStrategy(definition, hindsightSummary),
)

export const simulationCatalog = Object.fromEntries(
  simulationResults.map((result) => [result.definition.id, result]),
) as Record<StrategyId, SimulationResult>

export const leaderboard = [...simulationResults].sort(
  (left, right) => right.metrics.netReturn - left.metrics.netReturn,
)
