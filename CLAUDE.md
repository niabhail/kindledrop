# Kindledrop - Claude Code Instructions

## Project Context
Self-hosted news delivery service for Kindle. Uses Calibre CLI for EPUB generation.

## Code Conventions

### Python
- Python 3.12+ features allowed (type hints, match statements)
- Async functions for all I/O operations
- Use `Annotated` for FastAPI dependency injection
- SQLAlchemy 2.0 style (mapped_column, select())

### File Organization
- Models in `app/models/` with relationships defined
- Services in `app/services/` for business logic
- API routes in `app/api/` return JSON
- UI routes in `app/ui/` return HTML templates

### Testing
- Use pytest-asyncio for async tests
- Fixtures in `tests/conftest.py`
- Mock external services (Calibre, SMTP)

## Current Phase
MVP feature-complete with optimizations:
- Delivery engine (fetch → generate → email)
- SMTP integration with size validation
- APScheduler with polling job architecture
- Automatic scheduled deliveries (daily, weekly, interval)
- Timezone-aware scheduling
- Enhanced dashboard with status widgets
- Recipe browser with search
- Settings page with SMTP testing
- Error handling with retry support
- Same-day duplicate detection (SKIPPED status + Force Send)
- EPUB image compression with Pillow
- Data retention cleanup (EPUBs 24h, records 30 days)

## Post-MVP (Future)
- RSS feed support (custom URLs)
- Multi-user support
- Recipe credentials (for paywalled sites)
- Custom .recipe file uploads
- Delivery preview
- Mobile-optimized UI
- Prometheus metrics

## Commands

```bash
# Run dev server
uv run uvicorn app.main:app --reload

# Run tests
uv run pytest -v

# Create migration
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head
```

## Key Files
- `app/services/calibre.py` - Calibre CLI wrapper
- `app/services/delivery.py` - Delivery engine (fetch → generate → email)
- `app/services/smtp.py` - Email sending with size validation
- `app/services/scheduler.py` - APScheduler service (polling job)
- `app/services/auth.py` - Authentication logic
- `app/models/` - Database models
- `app/ui/routes.py` - All HTML page routes
