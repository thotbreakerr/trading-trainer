import type {
  AccountInfo,
  BackfillProgressInfo,
  BarsResponse,
  BriefingData,
  CompleteResponse,
  KeysStatus,
  LessonDetail,
  LessonListItem,
  MarketDayState,
  OrderRequest,
  OrderResult,
  RecapData,
  SessionBarsResponse,
  SessionInfo,
  SessionTrade,
  SizingResult,
  StepResponse,
  SymbolsResponse,
  Timeframe,
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
  stepSession: (id: string, bars: number) =>
    postJson<StepResponse>(`/api/sessions/${id}/step?bars=${bars}`),
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
  sessionTrades: (sessionId: string) =>
    getJson<{ trades: SessionTrade[] }>(`/api/sessions/${sessionId}/trades`),
  sizing: (body: { equity: number; entry: number; stop: number; risk_pct?: number }) =>
    postJson<SizingResult>('/api/sizing', body),
  marketDayState: () => getJson<MarketDayState>('/api/marketday/state'),
  actOnCallout: (id: string) =>
    postJson<{ orders: number[]; qty: number; grade: unknown }>(
      `/api/marketday/callouts/${id}/act`, {},
    ),
  briefing: (refresh = false) =>
    getJson<BriefingData>(`/api/briefing${refresh ? '?refresh=true' : ''}`),
  recap: (day?: string) => getJson<RecapData>(`/api/recap${day ? `?day=${day}` : ''}`),
}
