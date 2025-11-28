# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     DOCKER CONTAINER                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   FastAPI    │    │  APScheduler │    │   SQLite     │  │
│  │   (Web UI    │◄──►│  (Polling    │◄──►│   (Data)     │  │
│  │   + API)     │    │   Job)       │    │              │  │
│  └──────┬───────┘    └──────────────┘    └──────────────┘  │
│         │                   │                               │
│         │                   ▼                               │
│         │            ┌──────────────┐                      │
│         └───────────►│  Delivery    │                      │
│                      │  Engine      │                      │
│                      └──────┬───────┘                      │
│                             │                               │
│         ┌───────────────────┼───────────────────┐          │
│         ▼                   ▼                   ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Calibre    │    │   SMTP       │    │   Kindle     │  │
│  │   Wrapper    │    │   Client     │───►│   Device     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Web Framework | FastAPI | Async API and UI routes |
| UI | htmx + Jinja2 + Tailwind | Server-rendered, minimal JS |
| Database | SQLite + SQLAlchemy 2.0 | Async ORM with aiosqlite |
| Migrations | Alembic | Schema versioning |
| Auth | passlib + itsdangerous | Password hashing, signed cookies |
| Calibre | CLI subprocess | EPUB generation (async) |

## Project Structure

```
app/
├── main.py           # FastAPI app entry + lifespan hooks
├── config.py         # Pydantic settings
├── database.py       # SQLAlchemy async setup
├── dependencies.py   # FastAPI dependencies
├── models/           # SQLAlchemy ORM models
├── services/         # Business logic
│   ├── auth.py       # Authentication
│   ├── calibre.py    # Calibre CLI wrapper
│   ├── delivery.py   # Delivery engine pipeline
│   ├── scheduler.py  # APScheduler polling job
│   └── smtp.py       # Email sending
├── api/              # JSON API endpoints
└── ui/               # HTML routes
```

## Key Patterns

### Async Subprocess for Calibre
Calibre CLI runs via `asyncio.create_subprocess_exec` to avoid blocking the event loop.

### Database as Source of Truth
Subscriptions and schedules stored in SQLite. No in-memory state.

### Polling Job Scheduler
APScheduler runs a single polling job every 60 seconds that queries `next_run_at <= now()`.
- Database is source of truth (no sync issues)
- Subscription changes are instant (no job recreation)
- Skips missed deliveries on restart (content is fetched live)
- Max 3 concurrent deliveries via semaphore

### Signed Cookie Sessions
Stateless sessions via `itsdangerous.URLSafeTimedSerializer`. No server-side session storage.

## Extension Points

### Adding New Subscription Types
1. Add enum value to `SubscriptionType`
2. Extend `CalibreWrapper` with new fetch method
3. Update delivery engine (Phase 2)

### Custom Calibre Recipes
Mount recipes directory in Docker, reference by path instead of built-in name.

### Database Migration
SQLAlchemy engine can be swapped to PostgreSQL by changing `DATABASE_URL`.
