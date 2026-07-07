// Request building + error-text extraction for the fetch wrapper.
// Node's global Response keeps the fakes honest (no jsdom needed).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

function stubFetch(response: Response) {
  const mock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', mock)
  return mock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request building', () => {
  it('keysStatus GETs /api/keys/status', async () => {
    const mock = stubFetch(jsonResponse({ present: true }))
    await api.keysStatus()
    expect(mock).toHaveBeenCalledWith('/api/keys/status')
  })

  it('saveKeys POSTs JSON with content type', async () => {
    const mock = stubFetch(jsonResponse({ data_ok: true, trading_ok: true }))
    await api.saveKeys('id', 'secret')
    const [url, init] = mock.mock.calls[0]
    expect(url).toBe('/api/keys')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body)).toEqual({ key_id: 'id', secret: 'secret' })
  })

  it('bars URI-encodes the symbol and carries tf/lookback', async () => {
    const mock = stubFetch(jsonResponse({ bars: [] }))
    await api.bars('BRK.B&X', '2026-06-16', '5m')
    expect(mock).toHaveBeenCalledWith('/api/bars?symbol=BRK.B%26X&day=2026-06-16&tf=5m&lookback=3')
  })

  it('stepSession POSTs with the bar count in the query', async () => {
    const mock = stubFetch(jsonResponse({ clock: 0, done: false, events: [] }))
    await api.stepSession('abc', 5)
    expect(mock.mock.calls[0][0]).toBe('/api/sessions/abc/step?bars=5')
    expect(mock.mock.calls[0][1].method).toBe('POST')
  })

  it('deleteSession uses the DELETE method', async () => {
    const mock = stubFetch(new Response(null, { status: 204 }))
    await api.deleteSession('abc')
    expect(mock).toHaveBeenCalledWith('/api/sessions/abc', { method: 'DELETE' })
  })

  it('POST without a body omits the body field', async () => {
    const mock = stubFetch(jsonResponse({ started: true }))
    await api.startBackfill()
    expect(mock.mock.calls[0][1].body).toBeUndefined()
  })
})

describe('error text extraction', () => {
  it('uses a string detail as-is', async () => {
    stubFetch(jsonResponse({ detail: 'no such session' }, { status: 404, statusText: 'Not Found' }))
    await expect(api.keysStatus()).rejects.toThrow('no such session')
  })

  it('stringifies an object detail', async () => {
    stubFetch(jsonResponse({ detail: { data_ok: false } }, { status: 400, statusText: 'Bad Request' }))
    await expect(api.keysStatus()).rejects.toThrow('{"data_ok":false}')
  })

  it('falls back to status text on a non-JSON body', async () => {
    stubFetch(new Response('<html>boom</html>', { status: 500, statusText: 'Internal Server Error' }))
    await expect(api.keysStatus()).rejects.toThrow('500 Internal Server Error')
  })
})
