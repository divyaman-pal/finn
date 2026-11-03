import { useEffect, useState } from 'react'
import { Brief } from './Brief'
import { Companies } from './Companies'
import { Dossier } from './Dossier'
import { Tripwires } from './Tripwires'
import { Icon } from './ui'

// Hash routes keep deep links working on any static host: #/  #/research  #/co/INFY  #/alerts
// (#/ledger and #/wires are the old names, kept so earlier links still work)
const route = () => window.location.hash.replace(/^#/, '') || '/'

export default function App() {
  const [path, setPath] = useState(route)
  useEffect(() => {
    const on = () => { setPath(route()); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const go = (p: string) => { window.location.hash = p }
  const back = () => (window.history.length > 1 ? window.history.back() : go('/'))

  const co = path.match(/^\/co\/([A-Za-z0-9&-]+)/)
  const tab = co || /^\/(research|ledger)/.test(path) ? 'research' : /^\/(alerts|wires)/.test(path) ? 'alerts' : 'brief'

  return (
    <div className="app">
      {co ? <Dossier symbol={co[1].toUpperCase()} back={back} />
        : tab === 'research' ? <Companies go={go} />
        : tab === 'alerts' ? <Tripwires />
        : <Brief go={go} />}
      <nav className="nav" aria-label="Main">
        <div className="nav-inner">
          <button aria-current={tab === 'brief' ? 'page' : undefined} onClick={() => go('/')}>{Icon.brief}Brief</button>
          <button aria-current={tab === 'research' ? 'page' : undefined} onClick={() => go('/research')}>{Icon.ledger}Research</button>
          <button aria-current={tab === 'alerts' ? 'page' : undefined} onClick={() => go('/alerts')}>{Icon.wires}Alerts</button>
        </div>
      </nav>
    </div>
  )
}
