import { useEffect, useMemo, useState } from 'react'
import { api, type Company } from './api'

let cache: Promise<Company[]> | null = null
const companies = () => (cache ??= api.companies().catch(() => { cache = null; return [] as Company[] }))

/** One search box for any NSE company: suggests known ones as you type, opens anything else on Enter. */
export function CompanySearch({ go, autoFocus }: { go: (p: string) => void; autoFocus?: boolean }) {
  const [list, setList] = useState<Company[]>([])
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState(false)
  useEffect(() => { companies().then(setList) }, [])

  const term = q.trim().toUpperCase()
  const hits = useMemo(() => !term ? [] : list.filter(c =>
    c.symbol.startsWith(term) || c.name.toUpperCase().includes(term)).slice(0, 5), [list, term])
  const open = (sym: string) => { setQ(''); go(`/co/${sym}`) }

  return (
    <div className="searchwrap">
      <form className="search" role="search" onSubmit={e => { e.preventDefault(); if (term) open(hits[0]?.symbol === term || !hits.length ? term : hits[0].symbol) }}>
        <input value={q} onChange={e => setQ(e.target.value)} onFocus={() => setFocus(true)} onBlur={() => window.setTimeout(() => setFocus(false), 150)}
          placeholder="Research any NSE company" aria-label="Company name or NSE symbol" autoFocus={autoFocus}
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
        <button type="submit">Open</button>
      </form>
      {focus && term && (
        <div className="suggest" role="listbox">
          {hits.map(c => (
            <button key={c.symbol} role="option" onMouseDown={() => open(c.symbol)}>
              <b>{c.name}</b><span className="muted small">{c.symbol}</span>
            </button>
          ))}
          {!list.some(c => c.symbol === term) && /^[A-Z0-9&-]{2,20}$/.test(term) && (
            <button role="option" onMouseDown={() => open(term)}>
              <b>Research {term}</b><span className="muted small">new · about two minutes</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}
