export type Session = 'pre' | 'rth' | 'post'
export type Timeframe = '1m' | '5m' | '15m' | '1h'

export interface ApiBar {
  t: number // epoch seconds UTC, bar start
  o: number
  h: number
  l: number
  c: number
  v: number
  s: Session
}

export interface DayMeta {
  day: string // YYYY-MM-DD (ET trading date)
  half_day: boolean
  session_open: number // epoch seconds
  open: number
  close: number
  session_close: number
}

export interface BarsResponse {
  symbol: string
  tf: string
  day: string
  bars: ApiBar[]
  days: DayMeta[]
  overlays: { vwap: Point[]; ema9: Point[]; ema20: Point[] }
  rvol: number | null
}

export interface SymbolStat {
  symbol: string
  last_price: number | null
  prior_close: number | null
  change_pct: number | null
  rvol: number | null
}

export interface SymbolsResponse {
  display_day: string | null
  state: 'pre' | 'open' | 'post' | 'closed' | 'unknown'
  symbols: SymbolStat[]
}

export interface Point {
  t: number
  v: number
}

export interface SessionInfo {
  id: string
  mode: string
  symbols: string[]
  day: string
  clock: number
  done: boolean
  start_at: number
  end_at: number
}

export interface StepResponse {
  clock: number
  cutoff: number
  done: boolean
  events: SimEvent[]
  new_bars: Record<string, ApiBar[]>
}

export interface SessionBarsResponse extends BarsResponse {
  clock: number
  done: boolean
  sma200: number | null
}

export interface SimEvent {
  kind: 'fill' | 'reject' | 'cancel' | 'eod_warning' | 'eod_flatten'
  ts: string
  symbol: string | null
  order_id: number | null
  detail: string
}

export interface AccountPosition {
  symbol: string
  qty: number
  avg_price: number
  last: number | null
  unrealized: number
  initial_stop: number | null
}

export interface WorkingOrder {
  id: number
  symbol: string
  side: 'buy' | 'sell'
  type: 'market' | 'limit' | 'stop'
  qty: number
  limit_price: number | null
  stop_price: number | null
  bracket_id: string | null
  role: string
  status: string
  fill_price: number | null
  reason: string | null
}

export interface AccountInfo {
  equity: number
  cash: number
  buying_power_left: number
  flattened: boolean
  positions: AccountPosition[]
  working_orders: WorkingOrder[]
}

export interface SessionTrade {
  symbol: string
  direction: 'long' | 'short'
  qty: number
  entry_ts: string
  entry_price: number
  exit_ts: string | null
  exit_price: number | null
  exit_reason: string | null
  r_multiple: number | null
}

export interface OrderResult {
  orders: WorkingOrder[]
  rejected: boolean
  reason: string | null
}

export interface SizingResult {
  shares: number
  risk_amount: number
  per_share_risk: number
  notional: number
  bp_capped: boolean
}

export interface OrderRequest {
  kind?: 'bracket' | 'market' | 'limit' | 'stop'
  side: 'buy' | 'sell'
  qty?: number
  entry_type?: 'market' | 'limit'
  limit_price?: number
  stop_price?: number
  target_price?: number
  risk_pct?: number
}

export type LessonStatus = 'available' | 'locked' | 'complete' | 'unavailable'

export interface LessonListItem {
  module: number
  title: string
  summary: string
  status: LessonStatus
  status_reason: string | null
  completed_steps: number
  total_steps: number
}

export interface LessonPause {
  at: string
  note: string
  ts: number
}

export type LessonStepType = 'action' | 'explain' | 'replay' | 'quiz' | 'practice'

export interface LessonStepData {
  index: number
  type: LessonStepType
  title: string
  body: string
  completed: boolean
  pointer?: { target: string; label: string }
  symbol?: string
  date?: string | null
  pauses?: LessonPause[]
  goal?: string | null
  question?: string
  choices?: string[]
}

export interface LessonDetail {
  module: number
  title: string
  summary: string
  status: LessonStatus
  completed_steps: number
  total_steps: number
  chart: { symbol: string; date: string } | null
  steps: LessonStepData[]
}

export interface CompleteResponse {
  completed: boolean
  correct?: boolean
  explain?: string
}

export interface KeysStatus {
  present: boolean
}

export interface BackfillProgressInfo {
  state: 'idle' | 'running' | 'done' | 'error'
  current?: string | null
  symbols_done?: number
  total_symbols?: number
  bars_added?: number
  error?: string
  errors?: string[]
}
