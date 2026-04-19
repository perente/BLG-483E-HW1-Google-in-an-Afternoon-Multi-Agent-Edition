import { useState } from 'react'

function formatJobLabel(job) {
  if (!job.origin_url) return `Job #${job.job_id}`
  return job.origin_url.length > 32
    ? `Job #${job.job_id} - ${job.origin_url.slice(0, 32)}...`
    : `Job #${job.job_id} - ${job.origin_url}`
}

export default function SearchForm({ onSearch, loading, jobs }) {
  const [query, setQuery] = useState('')
  const [jobId, setJobId] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    if (query.trim()) onSearch(query, jobId || null)
  }

  return (
    <div className="panel">
      <div className="panel__title">Search</div>

      <form onSubmit={handleSubmit} className="search-bar">
        <select
          className="job-select"
          value={jobId}
          onChange={e => setJobId(e.target.value)}
          title="Choose which crawl job to search"
        >
          <option value="">All Jobs</option>
          {(jobs || []).map(job => (
            <option key={job.job_id} value={job.job_id}>
              {formatJobLabel(job)}
            </option>
          ))}
        </select>

        <input
          className="field__input"
          type="text"
          placeholder="Enter search query..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />

        <button
          className="btn btn--search"
          type="submit"
          disabled={loading || !query.trim()}
        >
          {loading ? <span className="spinner" /> : 'Search'}
        </button>
      </form>
    </div>
  )
}
