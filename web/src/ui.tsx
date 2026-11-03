import { useEffect, type ReactNode } from 'react'
import type { Verdict } from './api'

export const VERDICTS: Verdict[] = ['delivered', 'missed', 'moved', 'dropped', 'pending']
export const VERDICT_TEXT: Record<Verdict, string> = {
  delivered: 'Delivered', missed: 'Missed', moved: 'Goalposts moved', dropped: 'Quietly dropped', pending: 'Pending',
}

export const crore = (v: number | null | undefined) =>
  v == null ? '—' : v >= 1e5 ? `₹${(v / 1e5).toFixed(2)}L Cr` : `₹${Math.round(v).toLocaleString('en-IN')} Cr`

/** Short form for tight spaces: ₹38.6k Cr, ₹3.33L Cr. */
export const croreShort = (v: number | null | undefined) =>
  v == null ? '—' : v >= 1e5 ? `₹${(v / 1e5).toFixed(2)}L Cr` : v >= 1e4 ? `₹${(v / 1e3).toFixed(1)}k Cr` : `₹${Math.round(v).toLocaleString('en-IN')} Cr`

export const pct =(v: number | null | undefined, digits = 1) =>
  v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}%`

export const tone = (v: number | null | undefined) => (v == null || v === 0 ? '' : v > 0 ? 'up' : 'down')

export function timeAgo(ts: string): string {
  const then = new Date(ts.length <= 19 ? ts + '+05:30' : ts).getTime()
  const h = (Date.now() - then) / 36e5
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`
  if (h < 24) return `${Math.round(h)}h ago`
  const d = Math.round(h / 24)
  return d === 1 ? 'yesterday' : `${d}d ago`
}

export function Delta({ v, suffix = '' }: { v: number | null | undefined; suffix?: string }) {
  return <span className={`num ${tone(v)}`}>{pct(v)}{suffix}</span>
}

export function VerdictTag({ v }: { v: Verdict }) {
  return <span className={`v ${v}`}>{VERDICT_TEXT[v]}</span>
}

export function Tally({ tally, showKey }: { tally: Partial<Record<Verdict, number>>; showKey?: boolean }) {
  const total = VERDICTS.reduce((s, v) => s + (tally[v] || 0), 0)
  if (!total) return null
  return (
    <>
      <div className="tally" role="img" aria-label={VERDICTS.map(v => `${tally[v] || 0} ${v}`).join(', ')}>
        {VERDICTS.map(v => tally[v] ? <i key={v} className={v} style={{ flex: tally[v] }} /> : null)}
      </div>
      {showKey && (
        <div className="tally-key">
          {VERDICTS.map(v => tally[v] ? <span key={v} className="small"><span className={`v ${v}`}>{tally[v]}</span> <span className="muted">{VERDICT_TEXT[v].toLowerCase()}</span></span> : null)}
        </div>
      )}
    </>
  )
}

/** Five bars, filled to the story's signal strength (0–2 scale). */
export function Signal({ score }: { score: number }) {
  const on = Math.max(1, Math.min(5, Math.round(score * 2.5)))
  return (
    <span className="signal" title={`Signal ${score.toFixed(2)}`} aria-label={`Signal strength ${on} of 5`}>
      {[0, 1, 2, 3, 4].map(i => <i key={i} className={i < on ? 'on' : ''} style={{ height: 5 + i * 2.5 }} />)}
    </span>
  )
}

export function Sheet({ onClose, children, label }: { onClose: () => void; children: ReactNode; label: string }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', k)
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', k); document.body.style.overflow = '' }
  }, [onClose])
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label}>
        <button className="grab" onClick={onClose} aria-label="Close" style={{ display: 'block' }} />
        {children}
      </div>
    </>
  )
}

/** Bars for amounts, an optional line for a % series on its own scale. Labels at the ends only: dense, not busy. */
export function Bars({ labels, values, line, lineLabel }: {
  labels: string[]; values: (number | null)[]; line?: (number | null)[] | null; lineLabel?: string
}) {
  const W = 320, H = 96, pad = 4, n = values.length
  const max = Math.max(...values.map(v => v ?? 0), 1)
  const bw = (W - pad * 2) / n
  const lv = (line || []).filter((v): v is number => v != null)
  const lmin = Math.min(...lv), lmax = Math.max(...lv)
  const ly = (v: number) => H - 14 - ((v - lmin) / (lmax - lmin || 1)) * (H - 34)
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H + 14}`} role="img" aria-label="trend chart">
      {values.map((v, i) => {
        const h = v && v > 0 ? (v / max) * (H - 20) : 0
        return <rect key={i} x={pad + i * bw + bw * 0.18} y={H - h} width={bw * 0.64} height={h} rx={2}
          fill={i === n - 1 ? 'var(--ink)' : 'var(--rule-2)'} />
      })}
      {line && lv.length > 1 && (
        <>
          <polyline fill="none" stroke="var(--accent)" strokeWidth={1.6} strokeLinejoin="round"
            points={line.map((v, i) => v == null ? '' : `${pad + i * bw + bw / 2},${ly(v)}`).filter(Boolean).join(' ')} />
          {line.map((v, i) => v == null ? null : <circle key={i} cx={pad + i * bw + bw / 2} cy={ly(v)} r={i === n - 1 ? 2.8 : 1.6} fill="var(--accent)" />)}
          {lineLabel && <text x={W - pad} y={10} textAnchor="end" fontSize={10} fill="var(--accent)" fontFamily="var(--sans)">{lineLabel}</text>}
        </>
      )}
      <text x={pad} y={H + 12} fontSize={10} fill="var(--ink-3)" fontFamily="var(--sans)">{labels[0]}</text>
      <text x={W - pad} y={H + 12} fontSize={10} fill="var(--ink-3)" textAnchor="end" fontFamily="var(--sans)">{labels[n - 1]}</text>
    </svg>
  )
}

export const Icon = {
  brief: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><path d="M4 5h16M4 10h10M4 15h16M4 20h7" /></svg>,
  ledger: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5" /></svg>,
  wires: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>,
  back: <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M15 6l-6 6 6 6" /></svg>,
  ext: <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M7 17L17 7M9 7h8v8" /></svg>,
}
