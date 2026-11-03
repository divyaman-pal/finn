import { useEffect, useState } from 'react'
import { api, type Company } from './api'
import { Tally } from './ui'

export function Companies({ go }: { go: (p: string) => void }) {
  const [list, setList] = useState<Company[] | null>(null)
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { api.companies().then(setList).catch(e => setErr(e.message)) }, [])

  const term = q.trim().toUpperCase()
  const shown = (list || []).filter(c => !term || c.symbol.includes(term) || c.name.toUpperCase().includes(term))
  const held = shown.filter(c => c.weight != null)
  const other = shown.filter(c => c.weight == null)
  const open = (e: React.FormEvent) => { e.preventDefault(); if (term) go(`/co/${term}`) }

  return (
    <>
      <header className="mast">
        <div className="mast-top"><span className="wordmark">FIN<i>N</i></span><span className="small muted">Promise ledger</span></div>
        <h1>Who keeps their word<em>?</em></h1>
        <div className="mast-sub">Four quarters of guidance, checked against what was delivered. Any NSE company.</div>
      </header>

      <form className="search" onSubmit={open} role="search">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Any NSE symbol, e.g. TCS" aria-label="NSE symbol"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
        <button type="submit">Open</button>
      </form>
      {term && !shown.some(c => c.symbol === term) && (
        <p className="small muted">Not built yet: press Open and FINN will read {term}'s filings now (about two minutes, first time only).</p>
      )}

      {err && <div className="err">{err}</div>}
      {!list && !err && <div className="skeleton" style={{ height: 300, marginTop: 12 }} />}

      {held.length > 0 && <Group title="Your book" items={held} go={go} />}
      {other.length > 0 && <Group title="Researched" items={other} go={go} />}
    </>
  )
}

function Group({ title, items, go }: { title: string; items: Company[]; go: (p: string) => void }) {
  return (
    <section className="section">
      <div className="section-title"><h3>{title}</h3><span className="small muted">{items.length}</span></div>
      {items.map(c => (
        <button key={c.symbol} className="co" onClick={() => go(`/co/${c.symbol}`)}>
          <div className="co-top">
            <b>{c.name}</b>
            <span className="small muted">{c.symbol}{c.weight != null ? ` · ${c.weight}%` : ''}</span>
          </div>
          {c.headline && <p>{c.headline}</p>}
          <Tally tally={c.tally} />
        </button>
      ))}
    </section>
  )
}
