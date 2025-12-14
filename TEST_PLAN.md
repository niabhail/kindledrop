# Kindledrop Test Plan

## Overview
Lightweight test suite focused on catching bugs early and validating critical functionality. Since development happens via Claude Code interface, automated tests are essential for regression detection.

## Current Test Analysis

### ✅ **Keep - Well-tested components:**

1. **`test_delivery.py`** (9 tests) - EXCELLENT
   - Covers full delivery pipeline (fetch → generate → email)
   - Tests error scenarios (missing Kindle email, missing SMTP config, Calibre failures)
   - Validates DB record creation and subscription tracking updates
   - **Action:** Keep as-is

2. **`test_scheduler.py`** (12 tests) - EXCELLENT
   - Comprehensive testing of `calculate_next_run()` logic
   - Daily, weekly, interval schedules with timezone handling
   - Edge cases (past time, future time, multiple days, invalid timezones)
   - Basic scheduler service start/stop tests
   - **Action:** Keep as-is

3. **`test_smtp.py`** (6 tests) - GOOD
   - SMTPConfig parsing
   - Email sending with mocking
   - File size validation (critical for Kindle limits)
   - Connection verification
   - **Action:** Keep as-is

4. **`test_subscriptions_api.py`** (5 tests) - GOOD
   - Recent addition with lightweight functional tests
   - Regression tests for enum/string handling bugs
   - **Action:** Keep as-is

### ⚠️ **Needs improvement:**

5. **`test_api.py`** (4 tests) - TOO MINIMAL
   - Only tests basic auth redirects and setup page
   - Missing critical API endpoints
   - **Action:** Expand (see recommendations below)

6. **`test_calibre.py`** (4 tests) - MINIMAL BUT ACCEPTABLE
   - Only tests parsing logic and caching
   - Calibre integration is mocked in delivery tests
   - **Action:** Keep as-is (Calibre is external tool, mocking is appropriate)

### 📋 **Fixtures (conftest.py)** - EXCELLENT
- Well-structured fixtures for DB, client, mocks
- Reusable test user and subscription fixtures
- **Action:** Keep as-is

## Recommended Test Additions

### Priority 1: Critical API Endpoints (Missing)

Add to `test_api.py`:

```python
# Subscription CRUD via API
- POST /api/subscriptions (create)
- GET /api/subscriptions (list)
- PATCH /api/subscriptions/{id} (toggle/update)
- DELETE /api/subscriptions/{id}
- POST /api/subscriptions/{id}/force-send

# Settings API
- GET /api/settings
- PUT /api/settings
- POST /api/settings/smtp-test

# Delivery API
- GET /api/deliveries (list with pagination)
```

### Priority 2: Authentication Flow

Add to `test_api.py`:

```python
# Setup flow
- POST /setup (create first user)
- Setup redirect when users exist

# Login/logout
- POST /login (valid credentials)
- POST /login (invalid credentials) ✅ already exists
- POST /logout

# Password reset
- POST /api/auth/forgot-password (request reset)
- POST /api/auth/reset-password (complete reset)
- Token expiry validation
```

### Priority 3: Edge Cases & Regression Tests

Add to new `test_edge_cases.py`:

```python
# Duplicate delivery detection (same day)
- Verify SKIPPED status when delivery already sent today
- Force send bypasses duplicate detection

# Data retention cleanup
- EPUBs deleted after 24h
- Delivery records kept for 30 days

# Schedule edge cases
- Subscription enabled/disabled transitions
- next_run_at calculation on toggle
- Timezone changes affecting schedules
```

### Priority 4: Integration Tests (Optional)

Add to new `test_integration.py`:

```python
# End-to-end delivery flow
- Scheduler picks up due subscription
- Delivery engine executes
- Subscription tracking updated
- EPUB cleanup scheduled

# Multi-subscription scenarios
- Multiple subscriptions for same user
- Different schedule types coexisting
```

## Tests to Remove

**None.** All current tests provide value and are lightweight.

## Testing Strategy

### Test Pyramid

```
     /\
    /  \  Few E2E Integration Tests (optional)
   /____\
  /      \
 / API &  \ Many Functional Tests (main focus)
/__________\
/            \
/ Unit Tests  \ Some focused unit tests
/______________\
```

### What to Test

**✅ DO test:**
- Critical business logic (delivery, scheduling, auth)
- API contracts (request/response formats)
- Error handling and validation
- Database state transitions
- Edge cases that caused bugs before

**❌ DON'T test:**
- External service internals (Calibre, SMTP)
- UI rendering (Jinja templates)
- Simple getters/setters
- Framework behavior (FastAPI, SQLAlchemy)

### Mocking Strategy

- Mock external services (Calibre, SMTP) ✅ already doing this
- Use in-memory SQLite for DB tests ✅ already doing this
- Mock time/dates for scheduler tests (consider adding `freezegun`)
- Real business logic, mocked I/O boundaries

## Test Maintenance

### When to Add Tests

1. **Before fixing a bug:** Write a failing test that reproduces the bug
2. **When adding features:** Add tests for new API endpoints/functionality
3. **When refactoring:** Ensure existing tests pass, add tests for new edge cases

### When to Update Tests

1. **API contracts change:** Update request/response validation tests
2. **Business logic changes:** Update delivery/scheduling tests
3. **Breaking changes:** Update all affected tests

### Test Naming Convention

```python
# Pattern: test_<function>_<scenario>_<expected>
test_delivery_missing_kindle_email_raises_config_error()
test_schedule_daily_past_time_returns_tomorrow()
test_api_create_subscription_valid_data_returns_201()
```

## Running Tests

### Local Development

```bash
# Install dev dependencies
uv sync --dev

# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_delivery.py -v

# Run specific test
uv run pytest tests/test_delivery.py::TestDeliveryEngine::test_execute_success -v

# Run with coverage
uv run pytest --cov=app --cov-report=term-missing
```

### CI/CD (Recommended Setup)

Create `.github/workflows/test.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v2
      - run: uv sync --dev
      - run: uv run pytest -v
```

## Test Coverage Goals

### Current Coverage (estimated)

- **Delivery Engine:** ~90% ✅
- **Scheduler Logic:** ~95% ✅
- **SMTP Service:** ~80% ✅
- **API Endpoints:** ~15% ⚠️ (needs improvement)
- **Auth Service:** ~10% ⚠️ (needs improvement)

### Target Coverage

- **Overall:** 70-80% (pragmatic, not exhaustive)
- **Critical paths:** 90%+ (delivery, scheduling, auth)
- **Utilities:** 60%+ (parsers, validators)
- **UI routes:** 30%+ (basic smoke tests)

## Quick Wins

### Immediate Actions (30 minutes)

1. **Fix test dependencies:**
   ```bash
   uv sync --dev
   uv run pytest -v  # Verify all tests pass
   ```

2. **Add basic API tests** to `test_api.py`:
   - Create subscription via API
   - List subscriptions via API
   - Update subscription via API

3. **Add GitHub Actions** workflow for automated testing

### Short-term (2-3 hours)

1. Add password reset flow tests
2. Add settings API tests
3. Add duplicate delivery detection test
4. Add force send test

### Long-term (as needed)

1. Add E2E integration tests
2. Add performance/load tests
3. Add data retention cleanup tests
4. Consider adding `pytest-cov` for coverage reports

## Summary

**Current state:** Strong foundation with excellent delivery and scheduler tests.

**Gaps:** Missing API endpoint tests and auth flow tests.

**Recommendation:** Focus on Priority 1 & 2 additions to reach 70% practical coverage. Keep tests fast and focused on catching real bugs.

**Philosophy:** Every test should answer "What bug does this prevent?" - avoid testing for the sake of coverage metrics.
