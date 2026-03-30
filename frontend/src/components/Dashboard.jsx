import React from 'react'

function Dashboard({ incidents }) {
  const total = incidents.length
  const autoExec = incidents.filter(i => i.decision === 'auto_executed').length
  const hitlApproved = incidents.filter(i => i.decision === 'hitl_approved').length
  const hitlRejected = incidents.filter(i => i.decision === 'hitl_rejected').length
  const skipped = incidents.filter(i => i.decision === 'skipped').length
  const anomalyTypes = {}
  incidents.forEach(i => { anomalyTypes[i.anomaly_type] = (anomalyTypes[i.anomaly_type] || 0) + 1 })
  const recent = [...incidents].reverse().slice(0, 5)

  const stats = [
    { label: 'Total Incidents', value: total, icon: '🔔', color: 'from-stellar-500 to-k8s-500' },
    { label: 'Auto-Remediated', value: autoExec, icon: '⚡', color: 'from-emerald-500 to-green-600' },
    { label: 'HITL Approved', value: hitlApproved, icon: '✅', color: 'from-blue-500 to-indigo-600' },
    { label: 'Blockchain Records', value: total, icon: '⛓️', color: 'from-stellar-400 to-violet-600' },
  ]

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s, i) => (
          <div key={i} className="glass-card p-5 hover:border-white/20 transition-all group">
            <div className="flex items-center justify-between mb-3">
              <span className="text-2xl">{s.icon}</span>
              <span className={`w-8 h-8 rounded-lg bg-gradient-to-br ${s.color} opacity-20 group-hover:opacity-40 transition-opacity`}></span>
            </div>
            <p className="text-3xl font-bold text-white">{s.value}</p>
            <p className="text-sm text-gray-400 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="glass-card p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Anomaly Distribution</h3>
          <div className="space-y-3">
            {Object.entries(anomalyTypes).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-stellar-500"></span>
                  <span className="text-sm text-gray-300">{type}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-1.5 bg-white/5 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-stellar-500 to-k8s-400 rounded-full" style={{ width: `${(count / total) * 100}%` }}></div>
                  </div>
                  <span className="text-xs text-gray-500 w-6 text-right">{count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Decision Breakdown</h3>
          <div className="space-y-3">
            <Bar label="Auto-Executed" count={autoExec} total={total} color="bg-emerald-500" />
            <Bar label="HITL Approved" count={hitlApproved} total={total} color="bg-blue-500" />
            <Bar label="HITL Rejected" count={hitlRejected} total={total} color="bg-red-500" />
            <Bar label="Skipped" count={skipped} total={total} color="bg-gray-500" />
          </div>
        </div>

        <div className="glass-card p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">⛓️ Blockchain Status</h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between text-sm"><span className="text-gray-400">Network</span><span className="chain-verified">Stellar Testnet</span></div>
            <div className="flex items-center justify-between text-sm"><span className="text-gray-400">Contract</span><span className="chain-verified">Soroban</span></div>
            <div className="flex items-center justify-between text-sm"><span className="text-gray-400">On-chain Records</span><span className="text-white font-semibold">{total}</span></div>
            <div className="flex items-center justify-between text-sm"><span className="text-gray-400">Verification</span><span className="text-emerald-400 text-xs font-medium">SHA-256 Hash Match</span></div>
            <div className="mt-4 p-3 bg-stellar-900/20 border border-stellar-500/20 rounded-xl">
              <p className="text-xs text-stellar-300">Every incident audit entry is hashed (SHA-256) and stored on Stellar blockchain for tamper-proof verification.</p>
            </div>
          </div>
        </div>
      </div>

      <div className="glass-card p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Recent Incidents</h3>
        <div className="space-y-3">
          {recent.map((inc, i) => (
            <div key={i} className="flex items-center gap-4 p-3 bg-white/[0.02] rounded-xl hover:bg-white/[0.05] transition-all">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-red-500/20 to-orange-500/20 flex items-center justify-center text-lg">
                {inc.anomaly_type === 'CrashLoopBackOff' ? '🔄' : inc.anomaly_type === 'OOMKilled' ? '💀' : inc.anomaly_type === 'PendingPod' ? '⏳' : '⚠️'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">{inc.anomaly_type}</p>
                <p className="text-xs text-gray-500 truncate">{inc.affected_resource}</p>
              </div>
              <span className={inc.decision === 'auto_executed' ? 'badge-auto' : inc.decision === 'hitl_rejected' ? 'badge-rejected' : 'badge-hitl'}>{inc.decision}</span>
              <span className="text-xs text-gray-600">{new Date(inc.timestamp).toLocaleTimeString()}</span>
            </div>
          ))}
          {recent.length === 0 && <p className="text-center text-gray-500 py-8">No incidents recorded yet.</p>}
        </div>
      </div>
    </div>
  )
}

function Bar({ label, count, total, color }) {
  const pct = total > 0 ? (count / total) * 100 : 0
  return (
    <div>
      <div className="flex justify-between text-sm mb-1"><span className="text-gray-400">{label}</span><span className="text-gray-300">{count}</span></div>
      <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden"><div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }}></div></div>
    </div>
  )
}

export default Dashboard
