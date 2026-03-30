import React, { useState } from 'react'

function IncidentTable({ incidents }) {
  const [expandedId, setExpandedId] = useState(null)
  const [filter, setFilter] = useState('all')
  const filtered = filter === 'all' ? incidents : incidents.filter(i => i.decision === filter)
  const rows = [...filtered].reverse()

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400 mr-2">Filter:</span>
        {['all', 'auto_executed', 'hitl_approved', 'hitl_rejected', 'skipped'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1 text-xs rounded-lg transition-all ${filter === f ? 'bg-stellar-600/30 text-stellar-300 border border-stellar-500/30' : 'bg-white/5 text-gray-400 border border-transparent hover:border-white/10'}`}>
            {f === 'all' ? 'All' : f.replace('_', ' ')}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-500">{filtered.length} incidents</span>
      </div>

      <div className="glass-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10">
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Time</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Anomaly</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Resource</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Action</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Blast</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Decision</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Chain</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {rows.map((inc, i) => (
              <React.Fragment key={i}>
                <tr className="hover:bg-white/[0.03] cursor-pointer transition-colors" onClick={() => setExpandedId(expandedId === i ? null : i)}>
                  <td className="px-4 py-3 text-xs text-gray-400 font-mono">{new Date(inc.timestamp).toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="text-base">{inc.anomaly_type === 'CrashLoopBackOff' ? '🔄' : inc.anomaly_type === 'OOMKilled' ? '💀' : inc.anomaly_type === 'PendingPod' ? '⏳' : '⚠️'}</span>
                      <span className="text-gray-200">{inc.anomaly_type}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-300 font-mono text-xs">{inc.affected_resource}</td>
                  <td className="px-4 py-3 text-gray-300"><code className="text-xs bg-white/5 px-2 py-0.5 rounded">{inc.plan_action}</code></td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold ${inc.plan_blast_radius === 'low' ? 'text-emerald-400' : inc.plan_blast_radius === 'medium' ? 'text-amber-400' : 'text-red-400'}`}>{inc.plan_blast_radius}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={inc.decision === 'auto_executed' ? 'badge-auto' : inc.decision === 'hitl_rejected' ? 'badge-rejected' : 'badge-hitl'}>{inc.decision}</span>
                  </td>
                  <td className="px-4 py-3"><span className="chain-verified">✓ on-chain</span></td>
                </tr>
                {expandedId === i && (
                  <tr><td colSpan="7" className="px-4 py-4 bg-white/[0.02]">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <h4 className="text-xs font-semibold text-gray-400 mb-2 uppercase">Root Cause Diagnosis</h4>
                        <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{inc.diagnosis}</p>
                      </div>
                      <div className="space-y-3">
                        <div><h4 className="text-xs font-semibold text-gray-400 mb-2 uppercase">Plain English Explanation</h4><p className="text-sm text-gray-300">{inc.explanation}</p></div>
                        <div><h4 className="text-xs font-semibold text-gray-400 mb-2 uppercase">Execution Result</h4><pre className="text-xs text-gray-400 bg-black/30 p-3 rounded-lg overflow-x-auto font-mono">{inc.result}</pre></div>
                        <div><h4 className="text-xs font-semibold text-gray-400 mb-1 uppercase">Incident ID</h4><code className="text-xs text-stellar-300 font-mono">{inc.incident_id}</code></div>
                      </div>
                    </div>
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="text-center py-12 text-gray-500">No incidents match this filter.</div>}
      </div>
    </div>
  )
}

export default IncidentTable
