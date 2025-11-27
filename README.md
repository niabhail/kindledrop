# Kindledrop

Self-hosted news delivery to Kindle via email.

## Quick Start

```bash
# Clone and configure
git clone <repo-url>
cd kindledrop
cp .env.example .env
# Edit .env with your SECRET_KEY

# Run with Docker
docker-compose up -d

# Or run locally
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000 to set up your account.

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Session encryption key (generate with `openssl rand -hex 32`) |
| `DATABASE_URL` | No | Database connection string (default: SQLite) |
| `EPUB_DIR` | No | Directory for generated EPUBs |
| `TZ` | No | Timezone for container |

## Features

- Browse and subscribe to 2000+ Calibre news recipes
- Per-subscription scheduling (daily, weekly, interval)
- Custom RSS feed support
- Clean web interface

## Requirements

- Python 3.12+
- Calibre (for Docker, included in image)
- SMTP credentials (Mailjet, SendGrid, etc.)

## Development

```bash
# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linter
uv run ruff check .
```

## License

MIT
