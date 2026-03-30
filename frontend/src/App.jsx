import React, { useState, useEffect } from 'react'
import Dashboard from './components/Dashboard'
import IncidentTable from './components/IncidentTable'
import BlockchainVerifier from './components/BlockchainVerifier'

function App() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('dashboard')
  const [lastRefresh, setLastRefresh] = useState(new Date())

  const fetchIncidents = async () => {
    try {
      const res = await fetch('/api/audit-log')
      if (res.ok) { setIncidents(await res.json()) }
    } catch {
      try {
        const res = await fetch('/audit_log.json')
        if (res.ok) { setIncidents(await res.json()) }
      } catch (e) { console.log('Could not fetch incidents:', e) }
    } finally { setLoading(false); setLastRefresh(new Date()) }
  }

  useEffect(() => { fetchIncidents(); const i = setInterval(fetchIncidents, 10000); return () => clearInterval(i) }, [])

  const tabs = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'incidents', label: 'Incidents', icon: '🔍' },
    { id: 'blockchain', label: 'Blockchain', icon: '⛓️' },
  ]

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-white/10 bg-gray-950/80 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-stellar-500 to-k8s-500 flex items-center justify-center text-white font-bold text-lg">K8</div>
            <div>
              <h1 className="text-xl font-bold gradient-text">K8sWhisperer</h1>
              <p className="text-xs text-gray-500">Blockchain-Verified Audit Trail</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>Monitoring Active
            </div>
            <span className="text-xs text-gray-600">Last refresh: {lastRefresh.toLocaleTimeString()}</span>
            <button onClick={fetchIncidents} className="px-3 py-1.5 text-xs font-medium bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition-all">↻ Refresh</button>
          </div>
        </div>
      </header>

      <nav className="max-w-7xl mx-auto px-6 pt-6">
        <div className="flex gap-1 bg-white/5 rounded-xl p-1 w-fit">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === tab.id ? 'bg-stellar-600/30 text-stellar-300 shadow-lg shadow-stellar-500/10' : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'}`}>
              {tab.icon} {tab.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-stellar-500 border-t-transparent rounded-full animate-spin"></div>
            <span className="ml-3 text-gray-400">Loading incidents...</span>
          </div>
        ) : (
          <>
            {activeTab === 'dashboard' && <Dashboard incidents={incidents} />}
            {activeTab === 'incidents' && <IncidentTable incidents={incidents} />}
            {activeTab === 'blockchain' && <BlockchainVerifier incidents={incidents} />}
          </>
        )}
      </main>

      <footer className="border-t border-white/5 py-6 mt-12">
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between text-xs text-gray-600">
          <span>K8sWhisperer © 2026 — Autonomous K8s Incident Response</span>
          <span>Powered by Stellar Soroban • LangGraph • Groq</span>
        </div>
      </footer>
    </div>
  )
}

export default App
