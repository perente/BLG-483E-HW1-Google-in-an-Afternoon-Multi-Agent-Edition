import SearchResultCard from './SearchResultCard.jsx'

export default function SearchResultsList({ results, query, loading }) {
  if (results === null && !loading) {
    return (
      <div className="state-box">
        <span className="state-box__icon">Search</span>
        Search results will appear here.
      </div>
    )
  }

  if (loading && results === null) {
    return (
      <div className="state-box">
        <span className="spinner" style={{ margin: '0 auto 10px', display: 'block' }} />
        Searching...
      </div>
    )
  }

  if (results && results.length === 0) {
    return (
      <div className="state-box">
        <span className="state-box__icon">None</span>
        No results for <strong style={{ color: 'var(--text)' }}>"{query}"</strong>. Try a different term or wait for more pages to be indexed.
      </div>
    )
  }

  if (!results) return null

  return (
    <div>
      <div className="results-header">
        <span className="results-count">
          {results.length} result{results.length !== 1 ? 's' : ''} for{' '}
          <span style={{ color: 'var(--text)' }}>"{query}"</span>
          {loading && <span className="spinner" style={{ marginLeft: '8px' }} />}
        </span>
      </div>

      {results.map((result, index) => (
        <SearchResultCard key={result.relevant_url ?? result.url ?? index} result={result} />
      ))}
    </div>
  )
}
