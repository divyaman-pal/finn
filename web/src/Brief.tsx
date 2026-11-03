import { useEffect, useState } from 'react'
import { api, type Edition, type Story } from './api'
import { Signal, Delta, timeAgo, pct } from './ui'
import { StorySheet } from './StorySheet'

const WINDOWS = [{ h: 24, label: '24h' }, { h: 72, label: '3 days' }, { h: 168, label: 'Week' }]
const WORDS = ['Nothing', 'One thing', 'Two things', 'Three things', 'Four things', 'Five things', 'Six things', 'Seven things', 'Eight things']

function readWindow(): number {
  try { return Number(localStorage.getItem('finn.window')) || 24 } catch { return 24 }
}

export function Brief({ go }: { go: (path: string) => void }) {
  const [hours, setHours] = useState(readWindow)
  const [ed, setEd] = useState<Edition | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<Story | null>(null)

  useEffect(() => {
    setEd(null); setErr('')
    try { localStorage.setItem('finn.window', String(hours)) } catch { /* private mode */ }
    api.brief(hours).then(setEd).catch(e => setErr(e.message))
  }, [hours])

  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })
  const n = ed?.counts.matter ?? 0

  return (
    <>
      <header className="mast">
        <div className="mast-top">
          <span className="wordmark">FIN<i>N</i></span>
          <span className="small muted">{today}</span>
        </div>
        {ed ? (
          <>
            <h1>{WORDS[n] ?? `${n} things`} {n === 1 ? 'matters' : 'matter'}<em>.</em></h1>
            <div className="mast-sub">
              {ed.counts.filed} filed away · {ed.counts.filings} filings across your book in {WINDOWS.find(w => w.h === hours)?.label.replace('24h', 'the last 24 hours') ?? `${hours}h`}
            </div>
          </>
        ) : <div className="skeleton" style={{ height: 70, marginTop: 14 }} />}
      </header>

      <div className="toolbar">
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map(w => (
            <button key={w.h} aria-pressed={w.h === hours} onClick={() => setHours(w.h)}>{w.label}</button>
          ))}
        </div>
      </div>

      {ed && (
        <div className="strip" aria-label="Your holdings today">
          {ed.strip.map(t => (
            <button key={t.symbol} className={`tile ${t.story ? 'hot' : ''}`} onClick={() => go(`/co/${t.symbol}`)}>
              {t.story && <i className="dot" />}
              <b>{t.symbol}</b>
              <Delta v={t.ret} />
              <div className="small muted">{t.weight}%{t.vol_x && t.vol_x >= 1.5 ? ` · ${t.vol_x.toFixed(1)}× vol` : ''}</div>
            </button>
          ))}
        </div>
      )}

      {err && <div className="err">Couldn't load the brief: {err}</div>}
      {!ed && !err && [0, 1, 2].map(i => <div key={i} className="skeleton" style={{ height: 120, margin: '10px 0' }} />)}

      {ed && n === 0 && (
        <div className="quiet">
          <h2>A quiet {hours === 24 ? 'day' : 'stretch'}.</h2>
          <p className="muted">Nothing filed or traded in your book crossed the bar. {ed.counts.filed} routine items are filed away below.</p>
        </div>
      )}

      {ed?.stories.map((s, i) => (
        <div key={s.id} className={i === 0 ? 'lead' : ''}>
          <StoryCard s={s} onOpen={() => setOpen(s)} />
        </div>
      ))}

      {ed && ed.filed.length > 0 && (
        <details className="filed">
          <summary>
            <div className="filed-head">
              <h2>Filed away</h2>
              <span className="small muted">{ed.counts.filed} items · tap to open</span>
            </div>
          </summary>
          {ed.filed.map(g => (
            <details key={g.label} className="group">
              <summary><b>{g.label}</b><span className="muted num">{g.items.length}</span></summary>
              {g.items.map(it => (
                <div key={it.id} className="row">
                  <span className="sym">{it.symbol}</span>
                  <span style={{ flex: 1 }}>
                    {it.url ? <a href={it.url} target="_blank" rel="noreferrer">{it.headline}</a> : it.headline}
                  </span>
                  <span className="small muted">{timeAgo(it.ts)}</span>
                </div>
              ))}
            </details>
          ))}
        </details>
      )}

      {ed && (
        <p className="cost">
          This edition cost ₹{(ed.cost_usd * 84).toFixed(2)} to make at list prices
          {ed.counts.pending > 0 && ` · ${ed.counts.pending} filings still being read`}
        </p>
      )}

      {open && <StorySheet s={open} onClose={() => setOpen(null)} go={go} />}
    </>
  )
}

function StoryCard({ s, onOpen }: { s: Story; onOpen: () => void }) {
  const r = s.reaction
  const verified = s.card && s.card.kind === 'results' && s.card.verified
  return (
    <button className="story" onClick={onOpen}>
      <div className="story-meta">
        <span className="tag">{s.label}</span>
        <span className="who">{s.symbol}</span>
        {s.weight != null && <span className="small muted">{s.weight}% of book</span>}
        <span className="when">{timeAgo(s.ts)}</span>
      </div>
      <h3>{s.headline}</h3>
      {s.why && <p className="why">{s.why}</p>}
      <div className="story-foot">
        {r && (
          <span className={`pill ${r.ret > 0 ? 'up' : r.ret < 0 ? 'down' : ''}`}>
            {pct(r.ret)} {r.excess != null && Math.abs(r.excess - r.ret) > 0.3
              ? <span style={{ opacity: 0.75 }}>({Math.abs(r.excess) < 0.3 ? 'in line with Nifty' : `${pct(r.excess)} vs Nifty`})</span> : null}
          </span>
        )}
        {r?.vol_x != null && r.vol_x >= 1.5 && <span className="pill">{r.vol_x.toFixed(1)}× volume</span>}
        {verified && <span className="pill">✓ numbers verified</span>}
        {s.card?.kind === 'management_change' && s.card.bio && <span className="pill">bio inside</span>}
        <Signal score={s.score} />
      </div>
    </button>
  )
}
