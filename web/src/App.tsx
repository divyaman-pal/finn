import { useEffect, useState } from 'react'
import { Brief } from './Brief'
import { Companies } from './Companies'
import { Dossier } from './Dossier'
import { Tripwires } from './Tripwires'
import { Icon } from './ui'

// Hash routes keep deep links working on any static host: #/  #/ledger  #/co/INFY  #/wires
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
  const tab = co || path.startsWith('/ledger') ? 'ledger' : path.startsWith('/wires') ? 'wires' : 'brief'

  return (
    <div className="app">
      {co ? <Dossier symbol={co[1].toUpperCase()} back={back} />
        : tab === 'ledger' ? <Companies go={go} />
        : tab === 'wires' ? <Tripwires />
        : <Brief go={go} />}
      <nav className="nav" aria-label="Main">
        <div className="nav-inner">
          <button aria-current={tab === 'brief' ? 'page' : undefined} onClick={() => go('/')}>{Icon.brief}Brief</button>
          <button aria-current={tab === 'ledger' ? 'page' : undefined} onClick={() => go('/ledger')}>{Icon.ledger}Ledger</button>
          <button aria-current={tab === 'wires' ? 'page' : undefined} onClick={() => go('/wires')}>{Icon.wires}Tripwires</button>
        </div>
      </nav>
    </div>
  )
}
