// Types mirror the backend's JSON. Only the fields the UI reads are declared.

export type Verdict = 'delivered' | 'missed' | 'moved' | 'dropped' | 'pending'

export interface Reaction { date: string; ret: number; excess: number | null; vol_x: number | null; close?: number }

export interface ResultLine {
  label: string; now: number | null; qoq: number | null; yoy: number | null
  prev: number | null; year_ago: number | null; filled_from_screener?: string[]
}
export interface ResultsCard {
  kind: 'results'; quarter: string; lines: ResultLine[]; margin: number | null; lender: boolean
  source: { url: string; page: number | null }; verified: boolean
  check: { fq?: string; ok: boolean; source?: string; note?: string; on?: string } | null
  promises: { topic: string; verdict: Verdict; line: string }[]
}
export interface PeopleCard {
  kind: 'management_change'; person: string; role: string; direction: string | null
  bio?: string; previous?: string; sources?: { title: string; url: string }[]
}
export type Card = ResultsCard | PeopleCard | { kind: 'error'; error: string }

export interface Story {
  id: string; kind: 'filing' | 'market'; symbol: string; name: string; weight: number | null
  category: string; label: string; materiality: string; ts: string; headline: string; why: string
  url?: string; card?: Card | null; reaction: Reaction | null; score: number
  parts: { event: number; materiality: number; position: number; reaction: number }
  tripwire?: string; also: { headline: string; url?: string; ts?: string }[]
}
export interface Edition {
  window: { hours: number; since: string; until: string }
  counts: { matter: number; filed: number; filings: number; pending: number }
  stories: Story[]
  filed: { label: string; items: Story[] }[]
  strip: { symbol: string; weight: number; ret: number | null; vol_x: number | null; story: boolean }[]
  cost_usd: number
}

export interface Claim {
  id: string; kind: 'forward' | 'reported'; topic: string; statement: string; quote: string; page: number
  fq: string; source_url: string; source_kind: string
}
export interface Thread {
  topic: string; metric: string; verdict: Verdict; verdict_line: string
  promise_ids: string[]; evidence_ids: string[]; beat?: boolean
  check?: { quarter: string; target: number; actual: number; met: boolean }
}
export interface Ledger {
  status: 'ok' | 'no_sources'; note?: string; source_kind: string; headline: string
  calls: { fq: string; period: string; url: string; error?: string }[]
  claims: Record<string, Claim>; threads: Thread[]
  bull: { point: string; ids: string[] }[]; bear: { point: string; ids: string[] }[]
  model?: string
}
export interface Vitals {
  symbol: string; name: string; sector: string | null; industry: string | null; about: string | null
  ratios: Record<string, string>; weight: number | null; lender: boolean; basis: string
  latest_quarter: { fq?: string; revenue?: number; revenue_yoy?: number | null; ebitda_margin?: number | null; pat?: number; pat_yoy?: number | null }
  ttm: { revenue: number | null; pat: number | null }
  trajectory: {
    years: string[]; revenue: (number | null)[]; pat: (number | null)[]; op_margin: (number | null)[] | null
    revenue_cagr_5y: number | null; pat_cagr_5y: number | null
    quarters: { fq: string; revenue: number; pat: number; margin: number | null }[]
  }
  balance_sheet: { periods: string[]; de: (number | null)[]; working_capital_days: (number | null)[]; ratio_periods: string[] } | null
  cash_quality: { periods: string[]; cfo: (number | null)[]; fcf: (number | null)[]; cfo_to_pat: (number | null)[]; cfo_to_pat_5y: number | null; cfo_to_pat_years: number }
  shareholding: { periods: string[]; promoters: (number | null)[] }
  flags: { tone: 'good' | 'bad'; text: string }[]
}
export interface Dossier { status: 'ready' | 'building'; vitals: Vitals | null; ledger?: Ledger; questions?: string[] }

export interface Answer {
  answerable: boolean; answer: string
  cites: ({ id: string; kind: 'claim'; fq: string; page: number; url: string; source_kind?: string; quote: string }
    | { id: string; kind: 'number'; text: string })[]
}

export interface Company {
  symbol: string; name: string; sector: string | null; weight: number | null
  has_ledger: boolean; tally: Partial<Record<Verdict, number>>; headline: string | null
  price: number | null; ret: number | null; date: string | null
}
export interface Rule {
  id: string; kind: 'price_move' | 'volume_spike' | 'filing'; scope: string; threshold?: number
  categories?: string[]; on: boolean; label: string
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${r.status})`)
  }
  return r.json()
}

export const api = {
  brief: (hours: number) => get<Edition>(`/api/brief?hours=${hours}`),
  dossier: (symbol: string) => get<Dossier>(`/api/dossier/${encodeURIComponent(symbol)}`),
  companies: () => get<Company[]>('/api/companies'),
  rules: () => get<Rule[]>('/api/rules'),
  ask: async (symbol: string, q: string): Promise<Answer> => {
    const r = await fetch(`/api/ask/${encodeURIComponent(symbol)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q }),
    })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Request failed (${r.status})`)
    return r.json()
  },
  saveRule: (r: Rule) =>
    fetch(`/api/rules/${r.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(r) })
      .then(x => x.json() as Promise<Rule>),
}
