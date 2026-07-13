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

export interface StepDelta {
  symbol: string
  tf: Timeframe
  bars: ApiBar[]
  overlays: { vwap: Point[]; ema9: Point[]; ema20: Point[] }
  rvol: number | null
}

export interface StepResponse {
  clock: number
  cutoff: number
  done: boolean
  events: SimEvent[]
  new_bars: Record<string, ApiBar[]>
  delta: StepDelta | null
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

export interface GradeInfo {
  tier: 'Textbook' | 'Solid' | 'Risky' | 'Reckless'
  note: string | null
  checklist: { key: string; label: string; passed: boolean; detail: string }[]
}

export interface OrderResult {
  orders: WorkingOrder[]
  rejected: boolean
  reason: string | null
  grade: GradeInfo | null
  risk: RiskDecision | null
}

export interface RiskIssue {
  rule_key: string
  detail: string
  disposition: 'warned' | 'blocked'
}

export interface RiskPolicy {
  mode: 'coach' | 'enforce'
  max_risk_per_trade_pct: number
  max_daily_loss_r: number
  max_trades_per_day: number
  cooldown_minutes: number
  max_open_risk_pct: number
  require_protective_stop: boolean
}

export interface RiskUsage {
  closed_r: number
  trades: number
  open_risk_amount: number
  open_risk_pct: number | null
  cooldown_remaining_minutes: number
}

export interface RiskDecision {
  allowed: boolean
  mode: 'coach' | 'enforce'
  issues: RiskIssue[]
  proposed_risk_amount: number
  proposed_risk_pct: number
  usage: RiskUsage
  policy: RiskPolicy
}

export interface RiskStatus {
  policy: RiskPolicy
  usage: RiskUsage
  events: (RiskIssue & { action: string; ts: string })[]
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

export interface CalloutData {
  id: string
  locked: boolean
  symbol: string
  fired_ts: string
  status: string
  unlock_module?: number | null
  setup_type?: string
  direction?: 'long' | 'short'
  entry?: number | null
  stop?: number | null
  target?: number | null
  rr?: number | null
  grade?: GradeInfo | null
  watch_seconds_left?: number
  invalidated_reason?: string | null
  outcome?: string | null
  outcome_r?: number | null
  tradeable?: boolean
  context?: Record<string, unknown>
}

export interface MarketDayState {
  market: { state: string; display_day?: string; reason?: string }
  poll: {
    stale: boolean
    stale_since: string | null
    error: string | null
    last_success: string | null
  }
  trading_unlocked: boolean
  session: { day: string; clock: number; delay_minutes: number } | null
  callouts: CalloutData[]
  account: {
    equity: number
    positions: { symbol: string; qty: number; avg_price: number; unrealized: number }[]
    flattened: boolean
  } | null
  risk: RiskStatus | null
}

export interface BriefingCard {
  symbol: string
  last_price?: number | null
  gap_pct?: number | null
  premarket_rvol?: number | null
  premarket_high?: number | null
  premarket_low?: number | null
  prior_high?: number | null
  prior_low?: number | null
  prior_close?: number | null
  sma200?: number | null
  daily_trend?: string
  nearest_level?: { name: string; price: number; distance_pct: number }
  error?: string
}

export interface BriefingData {
  day: string
  half_day: boolean
  created_at: string
  cards: BriefingCard[]
  focus: { symbol: string; why: string }[]
  game_plan: {
    setups_in_play: string[]
    key_times: Record<string, { epoch: number; ct: string; et: string }>
    note: string
  }
}

export interface RecapLedgerItem {
  symbol: string
  fired_et: string
  setup_type: string
  direction: string
  entry: number | null
  stop: number | null
  target: number | null
  rr: number | null
  grade: string | null
  status: string
  taken: number
  user_grade?: string | null
  outcome: string | null
  outcome_r: number | null
  note: string | null
}

export interface RecapTrade {
  symbol: string
  direction: string
  qty: number
  entry_et: string
  entry_price: number
  exit_price: number | null
  exit_reason: string | null
  r_multiple: number | null
  grade: string | null
  review: { symbol: string; day: string; start_at: number }
}

export interface TrajectoryData {
  cumulative: Record<string, number | null>
  rolling_20: Record<string, number | null>
  grade_distribution: Record<string, number>
  grade_by_day: { day: string; grades: Record<string, number> }[]
  equity_curve_r: { day: string; cum_r: number }[]
}

export interface RecapData {
  day: string
  ledger: RecapLedgerItem[]
  ledger_computed_on_demand: boolean
  trades: RecapTrade[]
  plan_vs_reality: {
    taken: boolean
    focus_was?: string[]
    reality?: {
      symbol: string
      planned_gap_pct?: number | null
      day_change_pct?: number
      range_pct?: number
      broke_pdh?: boolean
      broke_pdl?: boolean
    }[]
  }
  trajectory: TrajectoryData
}

export interface JournalTrade {
  id: number
  mode: 'practice' | 'marketday' | 'drill' | 'scenario'
  day: string
  symbol: string
  direction: 'long' | 'short'
  qty: number
  entry_et: string
  entry_price: number
  exit_price: number | null
  exit_reason: string | null
  r_multiple: number | null
  grade: string | null
  setup_type: string | null
  replay: { symbol: string; day: string; start_at: number }
  review: TradeReview
}

export interface PredictionScore {
  status: 'pending_data' | 'pending_session' | 'late_not_scored' | 'scored'
  total: number | null
  direction_correct?: boolean
  actual_direction?: string
  day_move_pct?: number
  level_hit?: boolean
  brier?: number
  plan_points?: number
}

export interface BriefingPrediction {
  id: number
  day: string
  symbol: string
  direction: 'bullish' | 'bearish' | 'neutral'
  key_level: number | null
  setup: string
  invalidation: string
  confidence: number
  created_at: string
  updated_at: string
  locked_at: string | null
  is_late: boolean
  score: PredictionScore
}

export interface PredictionsResponse {
  day: string
  locked: boolean
  predictions: BriefingPrediction[]
}

export interface TradeReview {
  thesis: string
  notes: string
  confidence: number | null
  emotion: string
  mistakes: string[]
  tags: string[]
  reviewed: boolean
  updated_at: string | null
}

export interface TradeMarker {
  t: number
  price: number
  kind: 'entry' | 'exit'
  label: string
}

export interface TradeMetrics {
  mfe_r: number | null
  mae_r: number | null
  available_r: number | null
  entry_efficiency: number | null
  exit_efficiency: number | null
  duration_minutes: number | null
  bars_measured: number
  markers: TradeMarker[]
}

export interface JournalTradeDetail extends JournalTrade {
  metrics: TradeMetrics
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

export interface DrillSetupInfo {
  key: string
  label: string
  attempts: number
  taken: number
  passed: number
  grade_distribution: Record<string, number>
  taken_avg_outcome_r: number | null
  passed_avg_outcome_r: number | null
  by_day: { day: string; attempts: number; grades: Record<string, number> }[]
}

export interface DrillSetupsResponse {
  unlocked: boolean
  gate_module: number
  setups: DrillSetupInfo[]
}

export interface DrillRunInfo {
  run_id: string | null
  setup: string
  total: number
}

export type DrillNextResponse =
  | { done: true }
  | { done: false; attempt_id: string; idx: number; total: number; session: SessionInfo }

export interface DrillResolution {
  attempt_id: string
  idx: number
  total: number
  setup: {
    symbol: string
    day: string
    setup_type: string
    direction: 'long' | 'short'
    fired_ts: string
    fired_et: string
    entry: number | null
    stop: number | null
    target: number | null
    rr: number | null
    coach_grade: GradeInfo | null
  }
  outcome: { outcome: string; r_multiple: number | null; exit_price: number | null }
  user: {
    took: boolean
    grade: GradeInfo | null
    trade: {
      entry_price: number
      exit_price: number | null
      exit_reason: string | null
      r_multiple: number | null
    } | null
  }
}

export interface ScenarioSummary {
  id: string
  symbol: string
  day: string
  blind: boolean
  setup_type?: string
  direction?: 'long' | 'short'
  grade?: string | null
  fired_et?: string
}

export interface ScenarioResolution {
  id: string
  symbol: string
  day: string
  setup_type: string
  direction: 'long' | 'short'
  fired_ts: string
  fired_et: string
  entry: number
  stop: number
  target: number
  grade: string | null
  checklist: { label: string; passed: boolean; detail: string }[]
  outcome: string
  outcome_r: number | null
  exit_price: number | null
}

export interface ScenarioPlaylist {
  id: number
  name: string
  created_at: string
  items: number
}

export interface WorkoutItem {
  id: number
  run_id: number
  position: number
  setup: string
  label: string
  reps: number
  weakness_score: number
  reason: string
  status: 'pending' | 'complete'
  completed_at: string | null
}

export interface DailyWorkout {
  unlocked: boolean
  gate_module?: number
  run: { id: number; day: string; status: 'active' | 'complete'; created_at: string } | null
  items: WorkoutItem[]
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
