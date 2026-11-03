import { useEffect, useState } from 'react'
import { api, type Company } from './api'
import { CompanySearch } from './Search'
import { Delta, Tally } from './ui'

export function Companies({ go }: { go: (p: string) => void }) {
  const [list, setList] = useState<Company[] | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.companies().then(setList).catch(e => setErr(e.message)) }, [])

  const held = (list || []).filter(c => c.weight != null)
  const other = (list || []).filter(c => c.weight == null)
  const asOf = held.find(c => c.date)?.date

  return (
    <>
      <header className="mast">
        <div className="mast-top"><span className="wordmark">FIN<i>N</i></span><span className="small muted">Research</span></div>
        <h1>Who keeps their word<em>?</em></h1>
        <div className="mast-sub">Any NSE company, from its own calls and filings: four quarters of guidance checked against what was delivered.</div>
      </header>

      <CompanySearch go={go} />

      {err && <div className="err">{err}</div>}
      {!list && !err && <div className="skeleton" style={{ height: 300, marginTop: 12 }} />}

      {held.length > 0 && <Group title="Your portfolio" note={`${held.length} holdings${asOf ? ` · close ${asOf.slice(8)}/${asOf.slice(5, 7)}` : ''}`} items={held} go={go} />}
      {other.length > 0 && <Group title="Also researched" note={`${other.length}`} items={other} go={go} />}
    </>
  )
}

function Group({ title, note, items, go }: { title: string; note: string; items: Company[]; go: (p: string) => void }) {
  return (
    <section className="section">
      <div className="section-title"><h3>{title}</h3><span className="small muted">{note}</span></div>
      {items.map(c => (
        <button key={c.symbol} className="co" onClick={() => go(`/co/${c.symbol}`)}>
          <div className="co-top">
            <b>{c.name}</b>
            {c.price != null && (
              <span className="px num">₹{c.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })} <Delta v={c.ret} /></span>
            )}
          </div>
          <div className="small muted" style={{ marginTop: 2 }}>{c.symbol}{c.sector ? ` · ${c.sector}` : ''}{c.weight != null ? ` · ${c.weight}% of book` : ''}</div>
          {c.headline && <p>{c.headline}</p>}
          <Tally tally={c.tally} />
        </button>
      ))}
    </section>
  )
}
