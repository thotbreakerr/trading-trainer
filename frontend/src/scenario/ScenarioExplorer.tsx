import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ScenarioSummary } from '../lib/types'

export function ScenarioExplorer({ onStart }: { onStart: (scenario: ScenarioSummary) => void }) {
  const queryClient = useQueryClient()
  const [setup, setSetup] = useState('')
  const [direction, setDirection] = useState('')
  const [symbol, setSymbol] = useState('')
  const [blind, setBlind] = useState(true)
  const [playlistName, setPlaylistName] = useState('')
  const [playlistId, setPlaylistId] = useState<number | null>(null)
  const scenariosQ = useQuery({
    queryKey: ['scenarios', setup, direction, symbol, blind],
    queryFn: () => api.scenarios({ setup, direction, symbol, blind }),
  })
  const playlistsQ = useQuery({ queryKey: ['scenarioPlaylists'], queryFn: api.scenarioPlaylists })
  const playlistQ = useQuery({
    queryKey: ['scenarioPlaylist', playlistId, blind],
    queryFn: () => api.scenarioPlaylist(playlistId!, blind),
    enabled: playlistId != null,
  })
  const create = useMutation({
    mutationFn: () => api.createScenarioPlaylist(playlistName),
    onSuccess: async () => { setPlaylistName(''); await queryClient.invalidateQueries({ queryKey: ['scenarioPlaylists'] }) },
  })
  const firstPlaylist = playlistsQ.data?.playlists[0]
  const displayed = playlistId == null ? scenariosQ.data?.scenarios : playlistQ.data?.scenarios
  return <section className="scenario-explorer">
    <div className="scenario-title"><div><h2>Scenario explorer</h2><p className="muted">Filter cached history or keep outcomes hidden for an honest read.</p></div>
      <button className="btn-replay" onClick={() => void api.scenarios({ setup, direction, symbol, blind, refresh: true }).then(() => queryClient.invalidateQueries({ queryKey: ['scenarios'] }))}>↻ Re-index cache</button>
    </div>
    <div className="scenario-filters">
      <select value={playlistId ?? ''} onChange={(e) => setPlaylistId(e.target.value ? Number(e.target.value) : null)}><option value="">Browse catalog</option>{playlistsQ.data?.playlists.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.items})</option>)}</select>
      <select value={setup} onChange={(e) => setSetup(e.target.value)}><option value="">All setups</option>{scenariosQ.data?.setups.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
      <select value={direction} onChange={(e) => setDirection(e.target.value)}><option value="">Both directions</option><option value="long">Long</option><option value="short">Short</option></select>
      <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Symbol" />
      <label><input type="checkbox" checked={blind} onChange={(e) => setBlind(e.target.checked)} /> Blind mode</label>
    </div>
    <div className="playlist-bar"><input value={playlistName} onChange={(e) => setPlaylistName(e.target.value)} placeholder="New playlist name" /><button disabled={!playlistName.trim()} onClick={() => create.mutate()}>Create</button><span className="muted">{firstPlaylist ? `Saving to newest: ${firstPlaylist.name}` : 'Create a playlist to save scenarios'}</span></div>
    {scenariosQ.isPending && <p className="muted">Mining complete cached days…</p>}
    {scenariosQ.isError && <p className="banner">⚠ {String(scenariosQ.error)}</p>}
    <div className="scenario-grid">{displayed?.map((s, i) => <article key={s.id} className="scenario-card">
      <span className="muted">#{i + 1} · {s.day}</span><strong>{s.symbol}</strong>
      <span>{s.blind ? 'Setup hidden until reveal' : `${s.direction} ${s.setup_type?.replace(/_/g, ' ')} · ${s.grade ?? 'ungraded'}`}</span>
      <div className="actions"><button className="btn-primary" onClick={() => onStart(s)}>Start</button>{firstPlaylist && <button onClick={() => void api.addScenarioToPlaylist(firstPlaylist.id, s.id)}>Save</button>}</div>
    </article>)}</div>
    {displayed?.length === 0 && <p className="muted">No saved or indexed scenarios match. Re-index after more market days are cached.</p>}
  </section>
}
