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

**Quick Start:**
```bash
# Run all tests
uv run pytest -v

# Run specific file
uv run pytest tests/test_delivery.py -v

# Run specific test
uv run pytest tests/test_api.py::test_create_subscription_directly_in_db -v
```

**Current Test Coverage (53 tests, ~0.8s runtime):**
- `test_api.py` (19 tests) - API endpoints + regression tests
- `test_delivery.py` (8 tests) - Delivery pipeline, error handling
- `test_scheduler.py` (15 tests) - Schedule calculation, timezone logic
- `test_smtp.py` (7 tests) - SMTP sending, size validation
- `test_calibre.py` (4 tests) - Calibre wrapper utilities

**Testing Principles:**
- Use pytest-asyncio for async tests
- Fixtures in `tests/conftest.py` (db_session, client, authed_client, test_user, mocks)
- Mock external services (Calibre, SMTP) - never hit real services
- Use `authed_client` fixture for authenticated API tests
- Write regression tests when bugs are fixed (see test_api.py)
- Focus on happy path + critical error cases, not 100% coverage

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
- Password reset system (email-based + emergency script)

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
- `app/services/auth.py` - Authentication logic and password reset
- `app/models/` - Database models
- `app/ui/routes.py` - All HTML page routes
- `scripts/reset_password.py` - Emergency password reset tool

## Production Deployment (Docker)

### Critical Docker Concepts

**Volume Mounts vs Paths:**
- `docker-compose.prod.yml` uses a named volume: `kindledrop-data:/data`
- Inside container: paths like `/data/kindledrop.db` work correctly
- On host: the volume is managed by Docker, NOT in your code directory
- Database path in .env: `DATABASE_URL=sqlite+aiosqlite:////data/kindledrop.db` is correct for Docker

**Environment Variables:**
- Only environment variables listed in `docker-compose.prod.yml` are passed to container
- New environment variables must be added to the `environment:` section
- Example: `BASE_URL` must be explicitly added to docker-compose.prod.yml
- Container reads from both .env file AND docker-compose environment section

### Migration Best Practices

**ALWAYS run migrations inside the Docker container in production:**

```bash
# ✅ CORRECT - Inside container
docker exec kindledrop uv run alembic upgrade head

# ❌ WRONG - On host (will use wrong database path)
uv run alembic upgrade head
```

**Why?**
- Container has correct volume mounts for database access
- Container has correct Python environment and dependencies
- Host machine may use different database path (e.g., `./data` vs `/data`)

### Deployment Checklist

When deploying code changes to production:

1. **Pull latest code:**
   ```bash
   cd /opt/niabhail-platform/kindledrop
   git pull origin main
   ```

2. **Check for new environment variables:**
   - Look for changes in `docker-compose.prod.yml` environment section
   - Look for new settings in `app/config.py`
   - Update production `.env` file if needed

3. **Run migrations (if schema changed):**
   ```bash
   docker exec kindledrop uv run alembic upgrade head
   ```

4. **Restart container:**
   ```bash
   docker-compose -f docker-compose.prod.yml restart
   ```

5. **Verify deployment:**
   ```bash
   # Check logs for errors
   docker logs kindledrop --tail=50

   # Verify environment variables loaded
   docker exec kindledrop env | grep BASE_URL

   # Check health
   curl http://localhost:8000/
   ```

### Troubleshooting Production Issues

**Container can't find database:**
- Don't run migrations from host machine
- Database is in Docker volume, not host filesystem
- Use: `docker exec kindledrop <command>`

**Environment variable not available:**
- Check if variable is in `docker-compose.prod.yml` environment section
- Restart container after adding to docker-compose
- Verify with: `docker exec kindledrop env | grep VAR_NAME`

**Need to access production database:**
```bash
# Find the database in Docker volume
docker exec kindledrop ls -la /data/

# Open SQLite shell
docker exec -it kindledrop sqlite3 /data/kindledrop.db
```

### Password Reset

Two methods available:

1. **Email-based (standard):**
   - User clicks "Forgot password?" on login page
   - Requires SMTP configured and BASE_URL set
   - Token expires in 1 hour

2. **Direct reset (emergency):**
   ```bash
   docker exec kindledrop python scripts/reset_password.py USERNAME PASSWORD
   ```
   - Use when email method unavailable
   - Requires SSH access to server
   - Immediate password reset
