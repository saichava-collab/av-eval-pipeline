import { useEffect, useState, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'

const GO_API = import.meta.env.VITE_GO_API_URL || 'http://localhost:8080'
const PYTHON_API = import.meta.env.VITE_PYTHON_API_URL || 'http://localhost:8000'

function useInterval(callback, delayMs) {
  useEffect(() => {
    const id = setInterval(callback, delayMs)
    return () => clearInterval(id)
  }, [callback, delayMs])
}

export default function App() {
  const [summary, setSummary] = useState([])
  const [runs, setRuns] = useState([])
  const [queryLatencyMs, setQueryLatencyMs] = useState(null)
  const [error, setError] = useState(null)
  const [nVariants, setNVariants] = useState(1000)
  const [statusFilter, setStatusFilter] = useState('')
  const [triggering, setTriggering] = useState(false)
  const [lastRunResult, setLastRunResult] = useState(null)

  const fetchSummary = useCallback(async () => {
    try {
      const start = performance.now()
      const res = await fetch(`${GO_API}/api/v1/summary`)
      if (!res.ok) throw new Error(`summary request failed (${res.status})`)
      const data = await res.json()
      setSummary(data || [])
      setQueryLatencyMs(res.headers.get('X-Query-Latency-Ms') || (performance.now() - start).toFixed(2))
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  const fetchRuns = useCallback(async () => {
    try {
      const qs = statusFilter ? `?status=${statusFilter}&limit=50` : '?limit=50'
      const res = await fetch(`${GO_API}/api/v1/runs${qs}`)
      if (!res.ok) throw new Error(`runs request failed (${res.status})`)
      const data = await res.json()
      setRuns(data || [])
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [statusFilter])

  useEffect(() => { fetchSummary(); fetchRuns() }, [fetchSummary, fetchRuns])
  useInterval(() => { fetchSummary(); fetchRuns() }, 8000)

  const totals = summary.reduce(
    (acc, s) => ({
      total: acc.total + s.total,
      pass: acc.pass + s.pass_count,
      fail: acc.fail + s.fail_count,
      error: acc.error + s.error_count,
    }),
    { total: 0, pass: 0, fail: 0, error: 0 },
  )

  async function triggerEvaluation() {
    setTriggering(true)
    setLastRunResult(null)
    try {
      const res = await fetch(`${PYTHON_API}/api/v1/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n_variants: Number(nVariants), export_to_warehouse: true }),
      })
      if (!res.ok) throw new Error(`evaluation trigger failed (${res.status})`)
      const data = await res.json()
      setLastRunResult(data)
      await fetchSummary()
      await fetchRuns()
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setTriggering(false)
    }
  }

  const chartData = summary.map((s) => ({
    name: s.scenario_id,
    passRate: Number(s.pass_rate.toFixed(1)),
    category: s.category,
  }))

  return (
    <div className="console">
      <div className="console-header">
        <div>
          <p className="console-title">AV Testing &middot; Scenario Evaluation</p>
          <h1 className="console-heading">Simulation Evaluation Console</h1>
        </div>
        <div className="run-panel">
          <span className="status-pill"><span className="status-dot" /> LIVE</span>
          <input
            type="number"
            min="1"
            max="200000"
            value={nVariants}
            onChange={(e) => setNVariants(e.target.value)}
            title="Number of scenario variants to simulate"
          />
          <button className="run-btn" onClick={triggerEvaluation} disabled={triggering}>
            {triggering ? 'Running evaluation…' : 'Run evaluation batch'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">ERROR: {error}</div>}

      {lastRunResult && (
        <div className="panel">
          <p className="panel-title">Last Triggered Batch</p>
          <table>
            <tbody>
              <tr>
                <td>Batch ID</td><td>{lastRunResult.batch_id}</td>
                <td>Variants</td><td>{lastRunResult.total_variants}</td>
                <td>Ingest Time</td><td>{lastRunResult.ingest_seconds}s</td>
              </tr>
            </tbody>
          </table>
          <p className="footer-note">BigQuery: {lastRunResult.bigquery_export}</p>
          <p className="footer-note">Redshift: {lastRunResult.redshift_export}</p>
        </div>
      )}

      <div className="summary-grid">
        <div className="metric-card">
          <div className="metric-label">Total Runs</div>
          <div className="metric-value">{totals.total.toLocaleString()}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Pass</div>
          <div className="metric-value pass">{totals.pass.toLocaleString()}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Fail</div>
          <div className="metric-value fail">{totals.fail.toLocaleString()}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">P95 Query Latency</div>
          <div className="metric-value" style={{ color: 'var(--signal-active)' }}>
            {queryLatencyMs ? `${queryLatencyMs}ms` : '—'}
          </div>
        </div>
      </div>

      <div className="panel">
        <p className="panel-title">Pass Rate by Scenario</p>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e242b" />
            <XAxis dataKey="name" stroke="#8b95a1" fontSize={12} />
            <YAxis stroke="#8b95a1" fontSize={12} unit="%" domain={[0, 100]} />
            <Tooltip
              contentStyle={{ background: '#1a1f26', border: '1px solid #262c34', fontSize: 12 }}
              labelStyle={{ color: '#e8ebee' }}
            />
            <Bar dataKey="passRate" radius={[3, 3, 0, 0]}>
              {chartData.map((entry, idx) => (
                <Cell key={idx} fill={entry.passRate >= 90 ? '#3ddc97' : entry.passRate >= 70 ? '#ffb020' : '#ff5c5c'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <p className="panel-title">Recent Runs</p>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="PASS">PASS</option>
            <option value="FAIL">FAIL</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
        <table>
          <thead>
            <tr>
              <th>Scenario</th><th>Variant</th><th>Model</th><th>Status</th>
              <th>Min TTC (s)</th><th>Lane Dev (m)</th><th>Comfort</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r, i) => (
              <tr key={i}>
                <td>{r.scenario_id}</td>
                <td>{r.variant_id}</td>
                <td>{r.model_version}</td>
                <td><span className={`badge ${r.status}`}>{r.status}</span></td>
                <td>{r.min_ttc_seconds}</td>
                <td>{r.lane_deviation_meters}</td>
                <td>{r.comfort_score}</td>
                <td>{r.failure_reason || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
