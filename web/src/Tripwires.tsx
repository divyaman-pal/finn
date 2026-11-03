import { useEffect, useState } from 'react'
import { api, type Rule } from './api'

const SCOPES: [string, string][] = [['all', 'any holding'], ['large', 'any large cap'], ['mid', 'any mid cap'], ['small', 'any small cap']]
const CATS: [string, string][] = [
  ['results', 'Results'], ['M&A', 'M&A'], ['management_change', 'Leadership'], ['fund_raise', 'Fund raise'],
  ['litigation', 'Legal & regulatory'], ['credit_rating', 'Credit rating'], ['pledging', 'Pledges'],
  ['insider_trading', 'Insider trades'], ['capex', 'Capacity'], ['dividend', 'Dividends'],
]

export function Tripwires() {
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [saved, setSaved] = useState('')
  useEffect(() => { api.rules().then(setRules) }, [])

  const update = (r: Rule) => {
    setRules(rs => rs!.map(x => x.id === r.id ? r : x))
    api.saveRule(r).then(() => { setSaved(r.id); window.setTimeout(() => setSaved(''), 1200) })
  }
  const order = ['filings', 'move', 'volume', 'smallcap']
  const sorted = [...(rules || [])].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))

  return (
    <>
      <header className="mast">
        <div className="mast-top"><span className="wordmark">FIN<i>N</i></span><span className="small muted">Alerts</span></div>
        <h1>Interrupt me only if<em>…</em></h1>
        <div className="mast-sub">You decide what "unusual" means. Everything else waits for the Brief.</div>
      </header>
      {!rules && <div className="skeleton" style={{ height: 300, marginTop: 14 }} />}
      {sorted.map(r => (
        <div key={r.id} className="rule-card" data-on={r.on}>
          <div className="rule-head">
            <span className="eyebrow">{r.kind === 'filing' ? 'Filings' : r.kind === 'price_move' ? 'Price' : 'Volume'}{saved === r.id ? ' · saved' : ''}</span>
            <button className="toggle" role="switch" aria-checked={r.on} aria-label="Rule on" onClick={() => update({ ...r, on: !r.on })} />
          </div>
          <Sentence r={r} update={update} />
        </div>
      ))}
      <p className="small muted" style={{ marginTop: 16 }}>
        Moves are measured on end-of-day data and against the Nifty, so a market-wide fall doesn't look like news about your stock.
      </p>
    </>
  )
}

function Scope({ r, update }: { r: Rule; update: (r: Rule) => void }) {
  return (
    <span className="slot">
      <select value={r.scope} onChange={e => update({ ...r, scope: e.target.value })} aria-label="Which stocks">
        {SCOPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>▾
    </span>
  )
}

function Num({ r, update, step, unit, min }: { r: Rule; update: (r: Rule) => void; step: number; unit: string; min: number }) {
  const t = r.threshold ?? min
  return (
    <span className="slot">
      <button className="step" aria-label="Less" onClick={() => update({ ...r, threshold: Math.max(min, +(t - step).toFixed(1)) })}>−</button>
      <span className="num" style={{ padding: '0 6px' }}>{unit === '%' ? `±${t}%` : `${t}×`}</span>
      <button className="step" aria-label="More" onClick={() => update({ ...r, threshold: +(t + step).toFixed(1) })}>+</button>
    </span>
  )
}

function Sentence({ r, update }: { r: Rule; update: (r: Rule) => void }) {
  if (r.kind === 'price_move') return (
    <div className="sentence">When <Scope r={r} update={update} /> moves more than <Num r={r} update={update} step={0.5} unit="%" min={1} /> in a day.</div>
  )
  if (r.kind === 'volume_spike') return (
    <div className="sentence">When <Scope r={r} update={update} /> trades over <Num r={r} update={update} step={0.5} unit="x" min={1.5} /> its 20-day average volume.</div>
  )
  const cats = new Set(r.categories || [])
  return (
    <>
      <div className="sentence">Always surface a material filing about:</div>
      <div className="chips">
        {CATS.map(([v, l]) => (
          <button key={v} className="chip" aria-pressed={cats.has(v)}
            onClick={() => { const n = new Set(cats); n.has(v) ? n.delete(v) : n.add(v); update({ ...r, categories: [...n] }) }}>
            {l}
          </button>
        ))}
      </div>
    </>
  )
}
