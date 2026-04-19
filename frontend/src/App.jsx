import { useState, useEffect, useCallback, useRef } from 'react'
import CrawlForm from './components/CrawlForm.jsx'
import SearchForm from './components/SearchForm.jsx'
import JobsPanel from './components/JobsPanel.jsx'
import SearchResultsList from './components/SearchResultsList.jsx'

const POLL_INTERVAL_MS = 3000
const SEARCH_REFRESH_MS = 5000

export default function App() {
  const [view, setView] = useState('crawl')
  const [jobs, setJobs] = useState([])
  const [jobError, setJobError] = useState(null)
  const pollRef = useRef(null)

  const [results, setResults] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchJobId, setSearchJobId] = useState(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const searchRefreshRef = useRef(null)

  const activeJobs = jobs.filter(
    job => job.status === 'running' || job.status === 'queued' || job.status === 'pausing',
  )
  const hasActive = activeJobs.length > 0
  const atCap = activeJobs.length >= 2

  const pollJobs = useCallback(async () => {
    try {
      const res = await fetch('/jobs')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setJobs(data)
    } catch (err) {
      console.warn('Jobs poll failed:', err.message)
    }
  }, [])

  useEffect(() => {
    pollJobs()
    pollRef.current = setInterval(pollJobs, POLL_INTERVAL_MS)
    return () => clearInterval(pollRef.current)
  }, [pollJobs])

  async function handleStartCrawl({ origin, k, queueCap }) {
    setJobError(null)

    try {
      const res = await fetch('/index', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin,
          k: Number(k),
          queue_cap: Number(queueCap),
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `HTTP ${res.status}`)
      }
      await pollJobs()
      setView('crawl')
    } catch (err) {
      setJobError(err.message)
    }
  }

  async function handlePause(jobId) {
    setJobError(null)

    try {
      const res = await fetch(`/pause/${jobId}`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `HTTP ${res.status}`)
      }
      await pollJobs()
    } catch (err) {
      setJobError(err.message)
    }
  }

  async function handleResume(jobId) {
    setJobError(null)

    try {
      const res = await fetch(`/resume/${jobId}`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `HTTP ${res.status}`)
      }
      await pollJobs()
    } catch (err) {
      setJobError(err.message)
    }
  }

  async function runSearch(query, jobId = null, silent = false) {
    if (!query.trim()) return
    if (!silent) setSearchLoading(true)
    setSearchError(null)

    let endpoint = `/search?query=${encodeURIComponent(query.trim())}`
    if (jobId) {
      endpoint += `&job_id=${encodeURIComponent(jobId)}`
    }

    try {
      const res = await fetch(endpoint)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResults(data)
      setSearchQuery(query.trim())
      setSearchJobId(jobId)
      setView('search')
    } catch (err) {
      if (!silent) setSearchError(err.message)
    } finally {
      if (!silent) setSearchLoading(false)
    }
  }

  useEffect(() => {
    if (hasActive && results !== null && searchQuery) {
      searchRefreshRef.current = setInterval(() => {
        runSearch(searchQuery, searchJobId, true)
      }, SEARCH_REFRESH_MS)
    }

    return () => {
      if (searchRefreshRef.current) {
        clearInterval(searchRefreshRef.current)
        searchRefreshRef.current = null
      }
    }
  }, [hasActive, searchQuery, searchJobId, results !== null])

  return (
    <div className="app">
      <header className="header">
        <span className="header__wordmark">CRAWLER</span>
        <span className="header__sub">// multi-agent search system</span>
        <div
          className={`header__dot ${hasActive ? 'header__dot--active' : ''}`}
          title={hasActive ? `${activeJobs.length} active crawl` : 'Idle'}
        />
      </header>

      <div className="view-switch">
        <button
          type="button"
          className={`view-switch__btn ${view === 'crawl' ? 'view-switch__btn--active' : ''}`}
          onClick={() => setView('crawl')}
        >
          Crawl
        </button>

        <button
          type="button"
          className={`view-switch__btn ${view === 'search' ? 'view-switch__btn--active' : ''}`}
          onClick={() => setView('search')}
        >
          Search
        </button>
      </div>

      {view === 'crawl' && (
        <div className="grid2">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <CrawlForm onSubmit={handleStartCrawl} disabled={atCap} />
            {jobError && <div className="notice notice--error">Warning: {jobError}</div>}
          </div>
          <JobsPanel
            activeJobCount={activeJobs.length}
            jobs={jobs}
            onPause={handlePause}
            onResume={handleResume}
          />
        </div>
      )}

      {view === 'search' && (
        <div className="page-stack">
          <SearchForm onSearch={runSearch} loading={searchLoading} jobs={jobs} />
          {searchError && <div className="notice notice--error">Warning: {searchError}</div>}

          <div className="notice notice--info">
            {searchJobId
              ? `Searching only in Job #${searchJobId}.`
              : 'All Jobs searches across all indexed pages from every crawl job.'}
          </div>

          {hasActive && results !== null && (
            <div className="notice notice--info">
              Indexing active. UI search auto-refreshes every {SEARCH_REFRESH_MS / 1000}s to reflect latest data.
            </div>
          )}

          <SearchResultsList
            results={results}
            query={searchQuery}
            loading={searchLoading}
          />
        </div>
      )}
    </div>
  )
}
