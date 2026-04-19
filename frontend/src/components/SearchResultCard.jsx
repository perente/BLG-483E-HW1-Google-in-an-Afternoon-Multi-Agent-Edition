function decodeDisplayUrl(url) {
  if (!url) return ''
  try {
    return decodeURIComponent(url)
  } catch {
    return url
  }
}

export default function SearchResultCard({ result }) {
  const url = result.relevant_url || result.url
  const displayUrl = decodeDisplayUrl(url)
  const originUrl = decodeDisplayUrl(result.origin_url)

  return (
    <div className="result-card">
      {result.title && <div className="result-card__title">{result.title}</div>}

      <a
        className="result-card__url"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={displayUrl}
      >
        {displayUrl}
      </a>

      <div className="result-card__meta">
        <div className="result-card__meta-item">
          origin <span>{originUrl}</span>
        </div>
        <div className="result-card__meta-item">
          depth <span>{result.depth}</span>
        </div>
        {result.score != null && (
          <div className="result-card__meta-item">
            score <span>{typeof result.score === 'number' ? (Number.isInteger(result.score) ? result.score : result.score.toFixed(1)) : result.score}</span>
          </div>
        )}
      </div>
    </div>
  )
}
