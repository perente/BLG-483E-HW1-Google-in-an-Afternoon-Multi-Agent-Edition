function decodeDisplayUrl(url) {
  if (!url) return ''
  try {
    return decodeURIComponent(url)
  } catch {
    return url
  }
}

function StatusBadge({ status }) {
  if (!status) return <span className="badge badge--idle">idle</span>
  const cls = {
    running: 'badge--running',
    queued: 'badge--queued',
    pausing: 'badge--queued',
    done: 'badge--done',
    paused: 'badge--paused',
    error: 'badge--error',
  }[status] || 'badge--idle'
  return <span className={`badge ${cls}`}>{status}</span>
}

function KV({ label, value, highlight }) {
  return (
    <div className="kv-row">
      <span className="kv-row__key">{label}</span>
      <span className="kv-row__val" style={highlight ? { color: 'var(--amber)' } : {}}>
        {value ?? '-'}
      </span>
    </div>
  )
}

function JobCard({ activeJobCount, job, onPause, onResume }) {
  const isActive = job.status === 'running' || job.status === 'queued' || job.status === 'pausing'
  const isPaused = job.status === 'paused'
  const origin = decodeDisplayUrl(job.origin_url)
  const resumeDisabled = !isPaused || activeJobCount >= 2

  return (
    <div className="panel" style={{ marginBottom: '12px' }}>
      <div className="panel__title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Job #{job.job_id}</span>
        <StatusBadge status={job.status} />
      </div>

      <div className="stats">
        <div className="stat">
          <div className="stat__value">{job.indexed_pages?.toLocaleString() ?? 0}</div>
          <div className="stat__label">indexed</div>
        </div>
        <div className="stat">
          <div className="stat__value">{job.queue_depth?.toLocaleString() ?? 0}</div>
          <div className="stat__label">frontier backlog</div>
        </div>
      </div>

      <div>
        <KV label="origin" value={origin.length > 44 ? `${origin.slice(0, 44)}...` : origin} />
        <KV label="depth" value={job.max_depth} />
        <KV label="queue_cap" value={job.queue_cap?.toLocaleString()} />
        <KV label="back_pressure" value={job.back_pressure} highlight={job.back_pressure === 'active'} />
        {job.back_pressure_events > 0 && (
          <KV label="bp_events" value={job.back_pressure_events.toLocaleString()} highlight />
        )}
        <KV label="discovered" value={job.discovered_pages?.toLocaleString()} />
        <KV label="in_flight" value={job.in_flight} />
        <KV label="failed" value={job.failed_pages?.toLocaleString()} highlight={job.failed_pages > 0} />
        {job.error && <KV label="error" value={job.error} highlight />}
      </div>

      <div className="job-actions">
        <button
          className="btn btn--ghost"
          type="button"
          disabled={!isActive || job.status === 'pausing'}
          onClick={() => onPause(job.job_id)}
        >
          {job.status === 'pausing' ? 'Pausing...' : 'Pause'}
        </button>
        <button
          className="btn btn--ghost"
          type="button"
          disabled={resumeDisabled}
          onClick={() => onResume(job.job_id)}
        >
          Resume
        </button>
      </div>

      {isActive && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: 'var(--text-dim)' }}>
          <span className="spinner" />
          {job.status === 'pausing' ? 'pausing...' : 'crawling...'}
        </div>
      )}
    </div>
  )
}

export default function JobsPanel({ activeJobCount, jobs, onPause, onResume }) {
  if (!jobs || jobs.length === 0) {
    return (
      <div className="panel">
        <div className="panel__title">Jobs</div>
        <div className="state-box">
          <span className="state-box__icon">Jobs</span>
          No jobs yet. Start a crawl to see system state.
        </div>
      </div>
    )
  }

  const sorted = [...jobs].sort((a, b) => {
    const activeA = a.status === 'running' || a.status === 'queued' || a.status === 'pausing' ? 0 : 1
    const activeB = b.status === 'running' || b.status === 'queued' || b.status === 'pausing' ? 0 : 1
    if (activeA !== activeB) return activeA - activeB
    return b.job_id - a.job_id
  })

  const displayed = sorted.slice(0, 6)

  return (
    <div>
      <div className="panel__title" style={{ marginBottom: '8px' }}>
        Jobs ({jobs.filter(job => job.status === 'running' || job.status === 'queued' || job.status === 'pausing').length} active)
      </div>
      {displayed.map(job => (
        <JobCard
          key={job.job_id}
          activeJobCount={activeJobCount}
          job={job}
          onPause={onPause}
          onResume={onResume}
        />
      ))}
      {jobs.length > 6 && (
        <div style={{ fontSize: '11px', color: 'var(--text-dim)', textAlign: 'center' }}>
          +{jobs.length - 6} more jobs
        </div>
      )}
    </div>
  )
}
