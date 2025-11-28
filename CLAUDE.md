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
Phase 3 complete. Scheduling working:
- Delivery engine (fetch → generate → email)
- SMTP integration with size validation
- APScheduler with polling job architecture
- Automatic scheduled deliveries (daily, weekly, interval)
- Timezone-aware scheduling

## Next Phase (Phase 4)
- Calibre configuration UI
- Custom recipe management
- User-uploadable .recipe files

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
