import type {
  AccountInfo,
  BackfillProgressInfo,
  BarsResponse,
  BriefingData,
  BriefingPrediction,
  CompleteResponse,
  DrillNextResponse,
  DrillResolution,
  DrillRunInfo,
  DrillSetupInfo,
  DrillSetupsResponse,
  DailyWorkout,
  JournalTrade,
  JournalTradeDetail,
  TradeReview,
  KeysStatus,
  LessonDetail,
  LessonListItem,
  MarketDayState,
  OrderRequest,
  OrderResult,
  RecapData,
  RiskStatus,
  SessionBarsResponse,
  SessionInfo,
  SessionTrade,
  ScenarioPlaylist,
  ScenarioResolution,
  ScenarioSummary,
  SizingResult,
  StepResponse,
  SymbolsResponse,
  Timeframe,
  TrajectoryData,
} from './types'

async function errorText(r: Response): Promise<string> {
  try {
    const body = await r.json()
    const detail = body?.detail ?? body
    return typeof detail === 'string' ? detail : JSON.stringify(detail)
  } catch {
    return `${r.status} ${r.statusText}`
  }
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(await errorText(r))
  return r.json()
}

async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorText(r))
  return r.json()
}

async function patchJson<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorText(r))
  return r.json()
}

export const api = {
  keysStatus: () => getJson<KeysStatus>('/api/keys/status'),
  saveKeys: (key_id: string, secret: string) =>
    postJson<{ data_ok: boolean; trading_ok: boolean }>('/api/keys', { key_id, secret }),
  symbols: () => getJson<SymbolsResponse>('/api/symbols'),
  bars: (symbol: string, day: string, tf: Timeframe, lookback = 3) =>
    getJson<BarsResponse>(
      `/api/bars?symbol=${encodeURIComponent(symbol)}&day=${day}&tf=${tf}&lookback=${lookback}`,
    ),
  startBackfill: () => postJson<{ started: boolean }>('/api/backfill'),
  backfillProgress: () => getJson<BackfillProgressInfo>('/api/backfill/progress'),
  createSession: (symbol: string, day: string, startAt?: number) =>
    postJson<SessionInfo>('/api/sessions', { symbol, day, start_at: startAt }),
  stepSession: (id: string, bars: number, tf?: Timeframe) =>
    postJson<StepResponse>(`/api/sessions/${id}/step?bars=${bars}${tf ? `&tf=${tf}` : ''}`),
  sessionBars: (id: string, tf: Timeframe) =>
    getJson<SessionBarsResponse>(`/api/sessions/${id}/bars?tf=${tf}`),
  restartSession: (id: string) => postJson<SessionInfo>(`/api/sessions/${id}/restart`),
  deleteSession: (id: string) => fetch(`/api/sessions/${id}`, { method: 'DELETE' }),
  lessons: () => getJson<{ modules: LessonListItem[] }>('/api/lessons'),
  lesson: (module: number) => getJson<LessonDetail>(`/api/lessons/${module}`),
  completeStep: (
    module: number,
    step: number,
    body?: { answer?: number; session_id?: string },
  ) => postJson<CompleteResponse>(`/api/lessons/${module}/steps/${step}/complete`, body ?? {}),
  lessonSession: (module: number, step: number) =>
    postJson<SessionInfo>(`/api/lessons/${module}/steps/${step}/session`),
  placeOrder: (sessionId: string, body: OrderRequest) =>
    postJson<OrderResult>(`/api/sessions/${sessionId}/orders`, body),
  cancelOrder: (sessionId: string, orderId: number) =>
    fetch(`/api/sessions/${sessionId}/orders/${orderId}`, { method: 'DELETE' }),
  account: (sessionId: string) => getJson<AccountInfo>(`/api/sessions/${sessionId}/account`),
  riskStatus: (sessionId: string) => getJson<RiskStatus>(`/api/sessions/${sessionId}/risk`),
  sessionTrades: (sessionId: string) =>
    getJson<{ trades: SessionTrade[] }>(`/api/sessions/${sessionId}/trades`),
  sizing: (body: { equity: number; entry: number; stop: number; risk_pct?: number }) =>
    postJson<SizingResult>('/api/sizing', body),
  marketDayState: () => getJson<MarketDayState>('/api/marketday/state'),
  journalTrades: (filters?: {
    mode?: string
    symbol?: string
    grade?: string
    setup?: string
    tag?: string
    reviewed?: boolean
  }) => {
    const params = new URLSearchParams()
    Object.entries(filters ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== '') params.set(key, String(value))
    })
    const query = params.toString()
    return getJson<{ trades: JournalTrade[] }>(`/api/journal/trades${query ? `?${query}` : ''}`)
  },
  journalTrade: (id: number) => getJson<JournalTradeDetail>(`/api/journal/trades/${id}`),
  saveTradeReview: (id: number, review: Omit<TradeReview, 'updated_at'>) =>
    patchJson<{ trade_id: number; review: TradeReview }>(`/api/journal/trades/${id}/review`, review),
  journalStats: (mode?: string) =>
    getJson<TrajectoryData>(`/api/journal/stats${mode ? `?mode=${mode}` : ''}`),
  actOnCallout: (id: string) =>
    postJson<{ orders: number[]; qty: number; grade: unknown }>(
      `/api/marketday/callouts/${id}/act`, {},
    ),
  briefing: (refresh = false) =>
    getJson<BriefingData>(`/api/briefing${refresh ? '?refresh=true' : ''}`),
  predictions: (day: string) =>
    getJson<import('./types').PredictionsResponse>(`/api/briefing/predictions?day=${day}`),
  savePrediction: (body: {
    day: string
    symbol: string
    direction: string
    key_level: number | null
    setup: string
    invalidation: string
    confidence: number
  }) => postJson<BriefingPrediction>('/api/briefing/predictions', body),
  recap: (day?: string) => getJson<RecapData>(`/api/recap${day ? `?day=${day}` : ''}`),
  drillSetups: () => getJson<DrillSetupsResponse>('/api/drill/setups'),
  drillStartRun: (setup: string, count: number) =>
    postJson<DrillRunInfo>('/api/drill/runs', { setup, count }),
  drillNext: (runId: string) => postJson<DrillNextResponse>(`/api/drill/runs/${runId}/next`),
  drillResolve: (attemptId: string) =>
    postJson<DrillResolution>(`/api/drill/attempts/${attemptId}/resolve`),
  drillStats: () => getJson<{ setups: DrillSetupInfo[] }>('/api/drill/stats'),
  scenarios: (filters: {
    setup?: string
    direction?: string
    symbol?: string
    grade?: string
    blind?: boolean
    refresh?: boolean
  }) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== '') params.set(key, String(value))
    })
    return getJson<{
      scenarios: ScenarioSummary[]
      total: number
      setups: { key: string; label: string }[]
      index: { indexed: number; total: number }
    }>(`/api/scenarios?${params}`)
  },
  startScenario: (id: string) =>
    postJson<{ scenario_id: string; session: SessionInfo }>(`/api/scenarios/${id}/session`),
  scenarioResolution: (id: string) =>
    getJson<ScenarioResolution>(`/api/scenarios/${id}/resolution`),
  scenarioPlaylists: () => getJson<{ playlists: ScenarioPlaylist[] }>('/api/scenario-playlists'),
  scenarioPlaylist: (id: number, blind: boolean) =>
    getJson<{ playlist: ScenarioPlaylist; scenarios: ScenarioSummary[] }>(`/api/scenario-playlists/${id}?blind=${blind}`),
  createScenarioPlaylist: (name: string) =>
    postJson<ScenarioPlaylist>('/api/scenario-playlists', { name }),
  addScenarioToPlaylist: (playlistId: number, scenarioId: string) =>
    postJson(`/api/scenario-playlists/${playlistId}/items/${scenarioId}`),
  dailyWorkout: () => postJson<DailyWorkout>('/api/workouts/daily'),
  completeWorkoutItem: (runId: number, itemId: number) =>
    postJson<{ run_complete: boolean }>(`/api/workouts/${runId}/items/${itemId}/complete`),
}
