import type { AssetId, AssetMeta, MarketPoint } from '../types'

const initialPrices: Record<AssetId, number> = {
  SPY: 100,
  QQQ: 100,
  GLD: 100,
  TLT: 100,
}

const eventShocks: Record<number, Record<AssetId, number>> = {
  14: { SPY: -0.01, QQQ: -0.016, GLD: 0.008, TLT: 0.006 },
  15: { SPY: 0.007, QQQ: 0.012, GLD: -0.004, TLT: -0.002 },
  33: { SPY: 0.009, QQQ: 0.016, GLD: -0.005, TLT: -0.003 },
  48: { SPY: -0.008, QQQ: -0.013, GLD: 0.007, TLT: 0.006 },
  62: { SPY: 0.006, QQQ: 0.01, GLD: -0.001, TLT: 0.004 },
  75: { SPY: -0.007, QQQ: -0.01, GLD: 0.009, TLT: 0.008 },
}

const phases: Record<AssetId, number> = {
  SPY: 0.25,
  QQQ: 1.1,
  GLD: 2.6,
  TLT: 3.4,
}

const amplitudes: Record<AssetId, number> = {
  SPY: 0.0045,
  QQQ: 0.0068,
  GLD: 0.0042,
  TLT: 0.0036,
}

const regimeBlocks = [
  {
    until: 18,
    label: 'Growth chase',
    note: 'Momentum leads as risk assets absorb liquidity first.',
    drift: { SPY: 0.0011, QQQ: 0.0019, GLD: -0.0002, TLT: -0.0001 },
  },
  {
    until: 34,
    label: 'Volatility shock',
    note: 'Defensive assets catch the bid after a sharp growth unwind.',
    drift: { SPY: -0.0011, QQQ: -0.002, GLD: 0.0015, TLT: 0.0012 },
  },
  {
    until: 53,
    label: 'AI rebound',
    note: 'Growth recovers and trend-followers re-enter the tape.',
    drift: { SPY: 0.0014, QQQ: 0.0025, GLD: -0.0005, TLT: 0.0001 },
  },
  {
    until: 69,
    label: 'Rates reset',
    note: 'Duration and macro hedges regain importance as dispersion rises.',
    drift: { SPY: 0.0005, QQQ: 0.0007, GLD: 0.0011, TLT: 0.0015 },
  },
  {
    until: Number.POSITIVE_INFINITY,
    label: 'Defensive rotation',
    note: 'Capital rotates into hedges while growth leadership fades.',
    drift: { SPY: 0.0004, QQQ: -0.0007, GLD: 0.0014, TLT: 0.0012 },
  },
] as const

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function formatBusinessDay(date: Date) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date)
}

function buildBusinessDays(count: number) {
  const labels: string[] = []
  const cursor = new Date('2025-09-02T00:00:00')

  while (labels.length < count) {
    const weekday = cursor.getDay()

    if (weekday !== 0 && weekday !== 6) {
      labels.push(formatBusinessDay(cursor))
    }

    cursor.setDate(cursor.getDate() + 1)
  }

  return labels
}

function getRegime(day: number) {
  return regimeBlocks.find((block) => day < block.until) ?? regimeBlocks.at(-1)!
}

function wave(day: number, asset: AssetId) {
  const phase = phases[asset]
  const amplitude = amplitudes[asset]

  return (
    Math.sin(day / 3.5 + phase) * amplitude +
    Math.cos(day / 8.4 + phase * 1.4) * amplitude * 0.55
  )
}

function structuralTilt(day: number, asset: AssetId) {
  if (asset === 'QQQ') {
    return Math.sin(day / 5.4) * 0.0014
  }

  if (asset === 'GLD') {
    return Math.cos(day / 6.2) * 0.0011
  }

  if (asset === 'TLT') {
    return Math.sin(day / 7.1 + 0.8) * 0.0009
  }

  return Math.cos(day / 6.8 + 0.6) * 0.0007
}

function syntheticReturn(day: number, asset: AssetId) {
  const regime = getRegime(day)
  const jump = eventShocks[day]?.[asset] ?? 0
  const drift = regime.drift[asset]

  return clamp(drift + wave(day, asset) + structuralTilt(day, asset) + jump, -0.035, 0.035)
}

function buildMarketTape(length: number) {
  const labels = buildBusinessDays(length)
  const tape: MarketPoint[] = []
  let prices = { ...initialPrices }

  tape.push({
    index: 0,
    date: labels[0],
    regime: 'Warm start',
    note: 'Initial replay balance before any strategy takes risk.',
    prices: { ...prices },
    returns: { SPY: 0, QQQ: 0, GLD: 0, TLT: 0 },
  })

  for (let day = 1; day < length; day += 1) {
    const interval = day - 1
    const regime = getRegime(interval)
    const returns: Record<AssetId, number> = {
      SPY: syntheticReturn(interval, 'SPY'),
      QQQ: syntheticReturn(interval, 'QQQ'),
      GLD: syntheticReturn(interval, 'GLD'),
      TLT: syntheticReturn(interval, 'TLT'),
    }

    prices = {
      SPY: prices.SPY * (1 + returns.SPY),
      QQQ: prices.QQQ * (1 + returns.QQQ),
      GLD: prices.GLD * (1 + returns.GLD),
      TLT: prices.TLT * (1 + returns.TLT),
    }

    tape.push({
      index: day,
      date: labels[day],
      regime: regime.label,
      note: regime.note,
      prices: {
        SPY: Number(prices.SPY.toFixed(2)),
        QQQ: Number(prices.QQQ.toFixed(2)),
        GLD: Number(prices.GLD.toFixed(2)),
        TLT: Number(prices.TLT.toFixed(2)),
      },
      returns,
    })
  }

  return tape
}

export const assetMetas: AssetMeta[] = [
  {
    id: 'SPY',
    label: 'SPY',
    accent: '#68d391',
    description: 'Broad US equity beta.',
    volatility: 'Medium',
  },
  {
    id: 'QQQ',
    label: 'QQQ',
    accent: '#f6ad55',
    description: 'Higher-beta growth exposure.',
    volatility: 'High',
  },
  {
    id: 'GLD',
    label: 'GLD',
    accent: '#f6e05e',
    description: 'Macro hedge for stress regimes.',
    volatility: 'Medium',
  },
  {
    id: 'TLT',
    label: 'TLT',
    accent: '#63b3ed',
    description: 'Duration hedge in risk-off moves.',
    volatility: 'Low',
  },
]

export const assetIds = assetMetas.map((asset) => asset.id)

export const warmupPeriods = 6
export const startingCapital = 100_000
export const tradingFriction = 0.0015
export const marketTape = buildMarketTape(88)
