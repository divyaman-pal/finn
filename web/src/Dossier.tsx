import { useEffect, useState } from 'react'
import { api, type Claim, type Dossier as D, type Ledger, type Thread, type Verdict, type Vitals } from './api'
import { Bars, Delta, Icon, Tally, VerdictTag, crore, croreShort, pct } from './ui'

type Tab = 'ledger' | 'vitals' | 'case'

const BUILD_STEPS = ['Finding the last four earnings calls', 'Reading every guidance statement', 'Checking promises against reported numbers', 'Writing the ledger']

export function Dossier({ symbol, back }: { symbol: string; back: () => void }) {
  const [d, setD] = useState<D | null>(null)
  const [err, setErr] = useState('')
  const [tab, setTab] = useState<Tab>('ledger')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    let timer: number | undefined
    const load = () => api.dossier(symbol).then(x => {
      if (!alive) return
      setD(x)
      if (x.status === 'building') { timer = window.setTimeout(load, 4000); setTick(t => t + 1) }
    }).catch(e => alive && setErr(e.message))
    setD(null); setErr(''); setTick(0); load()
    return () => { alive = false; window.clearTimeout(timer) }
  }, [symbol])

  const v = d?.vitals
  const L = d?.ledger
  const tally: Partial<Record<Verdict, number>> = {}
  L?.threads?.forEach(t => { tally[t.verdict] = (tally[t.verdict] || 0) + 1 })

  return (
    <>
      <header className="dhead">
        <button className="back" onClick={back}>{Icon.back} Back</button>
        <div className="eyebrow">{v?.sector || 'Dossier'}{v?.weight ? ` · ${v.weight}% of your book` : ''}</div>
        <h1>{v?.name || symbol}</h1>
        {v && (
          <div className="facts">
            <span><b>{v.ratios['Current Price'] || '—'}</b></span>
            <span>Mkt cap <b>{(v.ratios['Market Cap'] || '—').replace(' Cr.', ' Cr')}</b></span>
            <span>P/E <b>{v.ratios['Stock P/E'] || '—'}</b></span>
            <span>{v.lender ? 'ROE' : 'ROCE'} <b>{v.ratios[v.lender ? 'ROE' : 'ROCE'] || '—'}</b></span>
          </div>
        )}
      </header>

      {err && <div className="err">{err}</div>}

      {d?.status === 'building' && (
        <div className="building">
          <h2>Building the {symbol} dossier from primary sources.</h2>
          <p className="muted small">First time for this company, so FINN reads its filings now. About two minutes; it's free to open after that.</p>
          <ul className="steps">
            {BUILD_STEPS.map((s, i) => {
              const at = Math.min(Math.floor(tick / 6), BUILD_STEPS.length - 1)
              return <li key={s} className={i < at ? 'done' : i === at ? 'now' : ''}>{i < at ? '✓' : i === at ? '◐' : '○'} {s}</li>
            })}
          </ul>
        </div>
      )}
      {!d && !err && <div className="skeleton" style={{ height: 240, marginTop: 16 }} />}

      {L && v && (
        <>
          {L.status === 'ok' ? (
            <>
              <p className="verdict-quote">“{L.headline}”</p>
              <Tally tally={tally} showKey />
            </>
          ) : <p className="muted" style={{ marginTop: 16 }}>{L.note}</p>}

          <div className="tabs" role="tablist" style={{ marginTop: 14 }}>
            {(['ledger', 'vitals', 'case'] as Tab[]).map(t => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                {t === 'ledger' ? 'Promise ledger' : t === 'vitals' ? 'Vitals' : 'Bull vs bear'}
              </button>
            ))}
          </div>

          {tab === 'ledger' && <LedgerView L={L} />}
          {tab === 'vitals' && <VitalsView v={v} />}
          {tab === 'case' && <CaseView L={L} />}
        </>
      )}
    </>
  )
}

function Receipt({ c }: { c: Claim }) {
  return (
    <a className="receipt" href={`${c.source_url}#page=${c.page}`} target="_blank" rel="noreferrer">
      {c.fq} {c.source_kind === 'ppt' ? 'presentation' : 'call'}, p.{c.page}
    </a>
  )
}

function LedgerView({ L }: { L: Ledger }) {
  const [open, setOpen] = useState<number | null>(0)
  if (L.status !== 'ok') return null
  const order: Verdict[] = ['missed', 'moved', 'dropped', 'delivered', 'pending']
  const threads = [...L.threads].sort((a, b) => order.indexOf(a.verdict) - order.indexOf(b.verdict))
  const missing = L.calls.filter(c => c.error)
  return (
    <div>
      {threads.map((t, i) => <ThreadRow key={i} t={t} L={L} open={open === i} toggle={() => setOpen(open === i ? null : i)} />)}
      <p className="small muted" style={{ marginTop: 14 }}>
        Built only from {L.source_kind === 'ppt' ? 'investor presentations (this company holds no earnings calls)' : 'earnings-call transcripts'}:{' '}
        {L.calls.filter(c => !c.error).map((c, i) => <span key={c.url}>{i > 0 && ', '}<a href={c.url} target="_blank" rel="noreferrer">{c.fq}</a></span>)}.
        {' '}Every quote is checked against its page.{missing.length > 0 && ` ${missing.map(m => m.fq).join(', ')}: ${missing[0].error}.`}
      </p>
    </div>
  )
}

function ThreadRow({ t, L, open, toggle }: { t: Thread; L: Ledger; open: boolean; toggle: () => void }) {
  const items = [...t.promise_ids.map(id => ({ id, promise: true })), ...t.evidence_ids.map(id => ({ id, promise: false }))]
    .map(x => ({ ...x, c: L.claims[x.id] })).filter(x => x.c)
    .sort((a, b) => a.c.fq.localeCompare(b.c.fq, undefined, { numeric: true }) || Number(b.promise) - Number(a.promise))
  const seen = new Set<string>()
  return (
    <div className="thread" data-open={open}>
      <button onClick={toggle} aria-expanded={open}>
        <span className="chev">›</span>
        <VerdictTag v={t.verdict} />{t.beat && <span className="small muted"> · beat the guide</span>}
        <h4>{t.topic}</h4>
        <p>{t.verdict_line}</p>
      </button>
      {open && (
        <>
          {t.check && (
            <p className="check">Checked against reported numbers: guided {t.check.target}, {t.check.quarter} came in at {t.check.actual}.</p>
          )}
          <div className="timeline">
            {items.filter(x => !seen.has(x.id) && seen.add(x.id)).map(x => (
              <div key={x.id} className={`tl ${x.promise ? 'promise-pt' : ''}`}>
                <span className="eyebrow">{x.promise ? 'Said' : 'Later'} · {x.c.fq}</span>
                <blockquote>“{x.c.quote}”</blockquote>
                <Receipt c={x.c} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function VitalsView({ v }: { v: Vitals }) {
  const q = v.trajectory.quarters
  const lq = v.latest_quarter
  const bs = v.balance_sheet
  const cq = v.cash_quality
  // margin line: operating margin, or PAT margin for lenders (EBITDA means nothing for a bank)
  const qLine = q.map(x => v.lender ? (x.revenue ? Math.round(x.pat / x.revenue * 1000) / 10 : null) : x.margin)
  return (
    <div>
      <div className="kpis">
        <div className="kpi"><span className="eyebrow">Revenue TTM</span><b>{croreShort(v.ttm.revenue)}</b><span className="muted">{lq.fq} <Delta v={lq.revenue_yoy} /> YoY</span></div>
        <div className="kpi"><span className="eyebrow">PAT TTM</span><b>{croreShort(v.ttm.pat)}</b><span className="muted">{lq.fq} <Delta v={lq.pat_yoy} /> YoY</span></div>
        <div className="kpi"><span className="eyebrow">{v.lender ? 'ROE' : 'Op. margin'}</span><b>{v.lender ? v.ratios['ROE'] : lq.ebitda_margin != null ? `${lq.ebitda_margin}%` : '—'}</b><span className="muted">{v.lender ? 'latest' : lq.fq}</span></div>
        <div className="kpi"><span className="eyebrow">5y revenue</span><b>{pct(v.trajectory.revenue_cagr_5y)}</b><span className="muted">CAGR</span></div>
        <div className="kpi"><span className="eyebrow">5y profit</span><b>{pct(v.trajectory.pat_cagr_5y)}</b><span className="muted">CAGR</span></div>
        <div className="kpi"><span className="eyebrow">Cash / profit</span><b>{cq.cfo_to_pat_5y != null ? `${Math.round(cq.cfo_to_pat_5y)}%` : '—'}</b><span className="muted">{cq.cfo_to_pat_years ? `${cq.cfo_to_pat_years}-yr` : 'n/a'}</span></div>
      </div>

      {v.flags.length > 0 && (
        <div className="section">
          <div className="section-title"><h3>Worth knowing</h3></div>
          {v.flags.map((f, i) => <div key={i} className={`flag ${f.tone}`}>{f.text}</div>)}
        </div>
      )}

      <div className="section">
        <div className="section-title"><h3>Last eight quarters</h3><span className="small muted">revenue bars · <span style={{ color: 'var(--accent)' }}>{v.lender ? 'PAT margin' : 'op. margin'}</span></span></div>
        <Bars labels={q.map(x => x.fq)} values={q.map(x => x.revenue)} line={qLine}
          lineLabel={qLine[qLine.length - 1] != null ? `${qLine[qLine.length - 1]!.toFixed(1)}%` : ''} />
      </div>

      <div className="section">
        <div className="section-title"><h3>The long arc</h3><span className="small muted">annual revenue · <span style={{ color: 'var(--accent)' }}>PAT</span></span></div>
        <Bars labels={v.trajectory.years} values={v.trajectory.revenue}
          line={v.trajectory.pat} lineLabel={crore(v.trajectory.pat[v.trajectory.pat.length - 1])} />
      </div>

      <div className="section">
        <div className="section-title"><h3>Does profit turn into cash?</h3><span className="small muted">operating cash ÷ PAT</span></div>
        <table className="res">
          <thead><tr><th>Year</th><th>Op. cash</th><th>Free cash</th><th>Cash/PAT</th></tr></thead>
          <tbody>
            {cq.periods.map((p, i) => (
              <tr key={p}><td>{p.replace('Mar ', 'FY')}</td><td className="num">{crore(cq.cfo[i])}</td><td className="num">{crore(cq.fcf[i])}</td>
                <td className={`num ${cq.cfo_to_pat[i] != null && cq.cfo_to_pat[i]! < 70 ? 'down' : ''}`}>{cq.cfo_to_pat[i] != null ? `${Math.round(cq.cfo_to_pat[i]!)}%` : '—'}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      {bs && (
        <div className="section">
          <div className="section-title"><h3>Balance sheet</h3></div>
          <table className="res">
            <thead><tr><th>As of</th><th>Debt/equity</th></tr></thead>
            <tbody>{bs.periods.map((p, i) => <tr key={p}><td>{p}</td><td className="num">{bs.de[i] != null ? `${bs.de[i]}×` : '—'}</td></tr>)}</tbody>
          </table>
          <table className="res" style={{ marginTop: 10 }}>
            <thead><tr><th>Year</th><th>Working-capital days</th></tr></thead>
            <tbody>{bs.ratio_periods.map((p, i) => <tr key={p}><td>{p.replace('Mar ', 'FY')}</td><td className="num">{bs.working_capital_days[i] ?? '—'}</td></tr>)}</tbody>
          </table>
        </div>
      )}

      {v.about && (
        <div className="section">
          <div className="section-title"><h3>The business</h3></div>
          <p className="small" style={{ color: 'var(--ink-2)' }}>{v.about.replace(/\[\d+\]/g, '').slice(0, 520)}{v.about.length > 520 ? '…' : ''}</p>
        </div>
      )}
      <p className="small muted">Figures in ₹ crore, {v.basis}, computed from standardised financials. No model touches these numbers.</p>
    </div>
  )
}

function CaseView({ L }: { L: Ledger }) {
  if (L.status !== 'ok') return null
  const side = (title: string, pts: Ledger['bull'], cls: string) => (
    <div className="side">
      <h3><span className={`v ${cls}`} /> {title}</h3>
      {pts.map((p, i) => (
        <div key={i} className="case">
          {p.point}
          <div className="ids">{p.ids.map(id => L.claims[id] ? <Receipt key={id} c={L.claims[id]} /> : null)}</div>
        </div>
      ))}
    </div>
  )
  return (
    <div>
      {side('Bull case', L.bull, 'delivered')}
      {side('Bear case', L.bear, 'missed')}
      <p className="small muted" style={{ marginTop: 14 }}>Grounded only in the company's own calls and reported numbers. No news, no broker notes, no outside knowledge.</p>
    </div>
  )
}
