import type { PeopleCard, ResultsCard, Story } from './api'
import { Sheet, VerdictTag, Delta, timeAgo, Icon } from './ui'

export function StorySheet({ s, onClose, go }: { s: Story; onClose: () => void; go: (p: string) => void }) {
  const card = s.card
  return (
    <Sheet onClose={onClose} label={s.headline}>
      <div className="story-meta">
        <span className="tag" style={{ color: 'var(--accent)' }}>{s.label}</span>
        <span className="who">{s.name}</span>
        <span className="when">{timeAgo(s.ts)}</span>
      </div>
      <h2>{s.headline}</h2>
      {s.why && <p style={{ color: 'var(--ink-2)', margin: '0 0 8px' }}>{s.why}</p>}

      {card?.kind === 'results' && <Results c={card} />}
      {card?.kind === 'management_change' && <Person c={card} />}

      {(s.reaction || s.tripwire) && (
        <div className="section">
          <div className="section-title"><h3>How the market took it</h3><span className="small muted">{s.reaction?.date}</span></div>
          {s.reaction && (
            <div className="facts">
              <span>Close <b className="num">{s.reaction.close ? `₹${s.reaction.close.toLocaleString('en-IN')}` : '—'}</b></span>
              <span>Day <b><Delta v={s.reaction.ret} /></b></span>
              {s.reaction.excess != null && <span>vs Nifty <b><Delta v={s.reaction.excess} /></b></span>}
              {s.reaction.vol_x != null && <span>Volume <b className="num">{s.reaction.vol_x.toFixed(1)}×</b> normal</span>}
            </div>
          )}
          {s.tripwire && <p className="small" style={{ marginTop: 8 }}>Your tripwire fired: {s.tripwire}</p>}
        </div>
      )}

      {s.also.length > 0 && (
        <div className="section">
          <div className="section-title"><h3>Same event, other filings</h3></div>
          {s.also.map((a, i) => (
            <div key={i} className="row" style={{ borderTop: i ? undefined : 0 }}>
              {a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.headline}</a> : a.headline}
            </div>
          ))}
        </div>
      )}

      <div className="section">
        <div className="section-title"><h3>Why this ranked here</h3></div>
        <p className="small muted" style={{ margin: 0 }}>
          Event {s.parts.event.toFixed(2)} × materiality {s.parts.materiality.toFixed(2)} × position {s.parts.position.toFixed(2)} × market reaction {s.parts.reaction.toFixed(2)} = <b style={{ color: 'var(--ink)' }}>{s.score.toFixed(2)}</b>.
          Bigger holdings, bigger moves and heavier events rise; routine paperwork sinks.
        </p>
      </div>

      <div className="story-foot" style={{ marginTop: 18 }}>
        {s.url && <a className="pill" href={s.url} target="_blank" rel="noreferrer">Read the filing {Icon.ext}</a>}
        <button className="pill" onClick={() => { onClose(); go(`/co/${s.symbol}`) }} style={{ background: 'var(--ink)', color: 'var(--paper)', borderColor: 'var(--ink)' }}>
          Open {s.symbol} dossier →
        </button>
      </div>
    </Sheet>
  )
}

function Results({ c }: { c: ResultsCard }) {
  const fq = c.check?.fq || c.quarter
  const src = c.check?.source === 'screener'
  return (
    <div className="section">
      <div className="section-title">
        <h3>{fq} at a glance</h3>
        <span className="small muted">₹ crore</span>
      </div>
      <table className="res">
        <thead><tr><th>Line</th><th>This qtr</th><th>QoQ</th><th>YoY</th></tr></thead>
        <tbody>
          {c.lines.map(l => (
            <tr key={l.label}>
              <td>{l.label}</td>
              <td className="num">{l.now == null ? '—' : Math.round(l.now).toLocaleString('en-IN')}</td>
              <td><Delta v={l.qoq} /></td>
              <td><Delta v={l.yoy} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="facts" style={{ marginTop: 8 }}>
        {c.margin != null && <span>{c.lender ? 'Pre-provision margin' : 'EBITDA margin'} <b className="num">{c.margin}%</b></span>}
        <span className="badge">
          {c.verified
            ? <><span className="ok">✓</span>{src ? `${c.check?.note}; numbers from the standardised series`
              : c.check?.on === 'pat' ? `Profit read from the filing${c.source.page ? `, p.${c.source.page}` : ''} and matches; revenue uses the standardised definition`
              : `Read from the filing${c.source.page ? `, p.${c.source.page}` : ''}; matches reported figures`}</>
            : <>Couldn't reconcile with reported figures; check the filing</>}
        </span>
      </div>

      {c.promises.length > 0 && (
        <div className="section">
          <div className="section-title"><h3>Promise check</h3><span className="small muted">from the last four calls</span></div>
          {c.promises.map((p, i) => (
            <div key={i} className="promise">
              <VerdictTag v={p.verdict} /> <span className="small muted">· {p.topic}</span>
              <p>{p.line}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Person({ c }: { c: PeopleCard }) {
  return (
    <div className="section">
      <div className="section-title">
        <h3>{c.person}</h3>
        <span className="small muted">{c.direction === 'leaving' ? 'leaving' : c.direction === 'joining' ? 'incoming' : ''} {c.role}</span>
      </div>
      {c.bio ? (
        <>
          <p style={{ margin: '0 0 8px', fontFamily: 'var(--serif)', fontSize: 16.5, lineHeight: 1.45 }}>{c.bio}</p>
          {c.sources && c.sources.length > 0 && (
            <div className="small muted">
              Background from{' '}
              {c.sources.map((s, i) => (
                <span key={s.url}>{i > 0 && ', '}<a href={s.url} target="_blank" rel="noreferrer">{new URL(s.url).hostname.replace('www.', '')}</a></span>
              ))}
            </div>
          )}
        </>
      ) : (
        <p className="small muted">{c.direction === 'leaving' ? 'An exit: the filing has the details.' : 'No reliable public background found.'}</p>
      )}
    </div>
  )
}
