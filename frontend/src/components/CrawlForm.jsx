import { useState } from 'react'

const MAX_QUEUE_CAP = 1000

export default function CrawlForm({ onSubmit, disabled }) {
  const [origin, setOrigin] = useState('')
  const [k, setK] = useState('2')
  const [queueCap, setQueueCap] = useState('500')
  const [error, setError] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (!origin.trim().startsWith('http')) {
      setError('URL must start with http:// or https://')
      return
    }

    const depth = parseInt(k, 10)
    if (Number.isNaN(depth) || depth < 0 || depth > 10) {
      setError('Depth must be a number between 0 and 10')
      return
    }

    const queue = parseInt(queueCap, 10)
    if (Number.isNaN(queue) || queue < 1 || queue > MAX_QUEUE_CAP) {
      setError(`Queue capacity must be a number between 1 and ${MAX_QUEUE_CAP}`)
      return
    }

    onSubmit({ origin: origin.trim(), k: depth, queueCap: queue })
  }

  return (
    <div className="panel">
      <div className="panel__title">Start Crawl</div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="field">
          <label className="field__label">Origin URL</label>
          <input
            className="field__input"
            type="url"
            placeholder="https://example.com"
            value={origin}
            onChange={e => setOrigin(e.target.value)}
            disabled={disabled}
            required
          />
        </div>

        <div className="field">
          <label className="field__label">Max Depth (k)</label>
          <input
            className="field__input"
            type="number"
            min="0"
            max="10"
            value={k}
            onChange={e => setK(e.target.value)}
            disabled={disabled}
          />
        </div>

        <div className="field">
          <label className="field__label">Queue Capacity</label>
          <input
            className="field__input"
            type="number"
            min="1"
            max={MAX_QUEUE_CAP}
            value={queueCap}
            onChange={e => setQueueCap(e.target.value)}
            disabled={disabled}
          />
        </div>

        {error && <div style={{ fontSize: '11px', color: 'var(--red)' }}>Warning: {error}</div>}

        <button
          className="btn btn--primary"
          type="submit"
          disabled={disabled}
          style={{ alignSelf: 'flex-start' }}
        >
          {disabled ? 'Max jobs reached' : 'Start Crawl'}
        </button>
      </form>
    </div>
  )
}
