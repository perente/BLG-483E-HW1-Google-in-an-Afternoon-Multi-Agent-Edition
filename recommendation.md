# Production Deployment Recommendations

This project is designed for local, educational use. A production deployment would
benefit from the following changes:

**Database**: Replace SQLite with a dedicated database server such as PostgreSQL.
This removes the single-writer limitation and provides a better foundation for
higher crawl volume, stronger operational tooling, and larger deployments.

**Task orchestration**: Replace in-process job execution with a task queue such as
Celery or Dramatiq, backed by Redis or RabbitMQ. This supports distributed crawling
across multiple machines, stronger worker isolation, more reliable recovery across
server restarts, and better operational control over crawl resources.

**Politeness and compliance**: Add `robots.txt` parsing and honor crawl-delay style
rules where applicable. Production crawling should also react more aggressively to
HTTP 429 responses and other signals that a target site wants reduced request volume.

**Frontend serving**: Serve the React build output behind a reverse proxy such as
nginx or Caddy rather than using the Vite development server. The Python API can
sit behind the same proxy so frontend and backend traffic share a single production
entry point.
