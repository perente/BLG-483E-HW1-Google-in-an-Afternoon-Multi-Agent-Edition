function StatusBadge({ status }) {
  if (!status) return <span className="badge badge--idle">idle</span>
  const cls = {
    running: 'badge--running',
    queued:  'badge--queued',
    done:    'badge--done',
    paused:  'badge--done',
    error:   'badge--error',
  }[status] || 'badge--idle'
  return <span className={`badge ${cls}`}>{status}</span>
}

function KV({ label, value, highlight }) {
  return (
    <div className="kv-row">
      <span className="kv-row__key">{label}</span>
      <span className="kv-row__val" style={highlight ? { color: 'var(--amber)' } : {}}>
        {value ?? '—'}
      </span>
    </div>
  )
}

export default function SystemStatusPanel({ job, isActive }) {
  if (!job) {
    return (
      <div className="panel">
        <div className="panel__title">Status</div>
        <div className="state-box">
          <span className="state-box__icon">◎</span>
          No active job.<br />Start a crawl to see system state.
        </div>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="panel__title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Status</span>
        <StatusBadge status={job.status} />
      </div>

      {/* Primary stats grid */}
      <div className="stats">
        {job.indexed_pages != null && (
          <div className="stat">
            <div className="stat__value">{job.indexed_pages.toLocaleString()}</div>
            <div className="stat__label">indexed pages</div>
          </div>
        )}
        {job.queue_depth != null && (
          <div className="stat">
            <div className="stat__value">{job.queue_depth.toLocaleString()}</div>
            <div className="stat__label">queue depth</div>
          </div>
        )}
      </div>

      {/* Key-value details */}
      <div>
        <KV label="job_id" value={job.job_id} highlight />

        {job.back_pressure != null && (
          <KV
            label="back_pressure"
            value={job.back_pressure}
            highlight={job.back_pressure === 'active'}
          />
        )}

        {job.discovered_pages != null && (
          <KV label="discovered" value={job.discovered_pages.toLocaleString()} />
        )}

        {job.in_flight != null && (
          <KV label="in_flight" value={job.in_flight} />
        )}

        {job.failed_pages != null && (
          <KV
            label="failed_pages"
            value={job.failed_pages.toLocaleString()}
            highlight={job.failed_pages > 0}
          />
        )}

        {job.error && (
          <KV label="error" value={job.error} highlight />
        )}
      </div>

      {isActive && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: 'var(--text-dim)' }}>
          <span className="spinner" />
          polling every 3s
        </div>
      )}
    </div>
  )
}
