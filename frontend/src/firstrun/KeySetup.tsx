import { useState } from 'react'
import { api } from '../lib/api'

/** One-time, unskippable Alpaca key entry (doc §13). Keys are validated with
 * live calls against both hosts before being written to .env. */
export function KeySetup({ onDone }: { onDone: () => void }) {
  const [keyId, setKeyId] = useState('')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.saveKeys(keyId, secret)
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="firstrun">
      <form className="card" onSubmit={submit}>
        <h1>Connect market data</h1>
        <p>
          This app runs every lesson and callout on <strong>real market data</strong> from
          Alpaca&apos;s free tier. Create a free paper-trading account at{' '}
          <a href="https://alpaca.markets" target="_blank" rel="noreferrer">
            alpaca.markets
          </a>{' '}
          and paste the API key pair here — they&apos;re validated with a live call, then
          stored locally in <code>.env</code>.
        </p>
        <label htmlFor="keyid">API Key ID</label>
        <input
          id="keyid"
          value={keyId}
          onChange={(e) => setKeyId(e.target.value)}
          autoComplete="off"
          required
        />
        <label htmlFor="secret">API Secret</label>
        <input
          id="secret"
          type="password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="off"
          required
        />
        {error && <div className="error-box">Validation failed: {error}</div>}
        <div className="actions">
          <button className="btn-primary" disabled={busy || !keyId || !secret}>
            {busy ? 'Validating…' : 'Validate & save'}
          </button>
        </div>
      </form>
    </div>
  )
}
