# Testing Quick Reference

## Current Status

✅ **43 tests passing** across 6 test files
⚡ **Fast execution:** ~0.6 seconds
🎯 **Coverage:** Strong on core services (delivery, scheduler, SMTP)
⚠️ **Gaps:** API endpoints and auth flows need expansion

## Running Tests

```bash
# Run all tests
uv run pytest -v

# Run specific file
uv run pytest tests/test_delivery.py -v

# Run specific test
uv run pytest tests/test_delivery.py::TestDeliveryEngine::test_execute_success -v

# Run with warnings suppressed
uv run pytest -v --disable-warnings

# Run matching pattern
uv run pytest -v -k "delivery"
```

## Test Files Overview

| File | Tests | Focus | Status |
|------|-------|-------|--------|
| `test_delivery.py` | 8 | Delivery engine, error handling | ✅ Excellent |
| `test_scheduler.py` | 15 | Schedule calculation, timezone logic | ✅ Excellent |
| `test_smtp.py` | 7 | SMTP sending, size validation | ✅ Good |
| `test_subscriptions_api.py` | 5 | API regression tests | ✅ Good |
| `test_api.py` | 4 | Setup, auth redirects | ⚠️ Needs expansion |
| `test_calibre.py` | 4 | Calibre wrapper utilities | ✅ Adequate |

## Adding New Tests

### 1. API Endpoint Test Template

```python
@pytest.mark.asyncio
async def test_endpoint_scenario(client: AsyncClient, test_user: User):
    """Test description."""
    response = await client.post(
        "/api/subscriptions",
        json={"source": "test_recipe", "name": "Test"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source"] == "test_recipe"
```

### 2. Service Logic Test Template

```python
async def test_service_scenario(db_session: AsyncSession, test_user: User):
    """Test description."""
    from app.services.delivery import DeliveryEngine

    engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)
    result = await engine.execute(db=db_session, ...)

    assert result.status == DeliveryStatus.SENT
```

### 3. Error Handling Test Template

```python
async def test_error_scenario(db_session: AsyncSession):
    """Test error is raised when condition occurs."""
    with pytest.raises(CustomError, match="expected message"):
        await some_function_that_should_fail()
```

## Fixtures Available

From `conftest.py`:

- `db_engine` - In-memory SQLite database engine
- `db_session` - Database session for tests
- `client` - HTTP client for API tests
- `test_user` - Pre-created user with SMTP config
- `test_subscription` - Pre-created subscription for test_user
- `mock_calibre` - Mocked Calibre service
- `mock_smtp` - Mocked SMTP sending
- `mock_smtp_connection` - Mocked SMTP connection test
- `mock_calibre_fetch` - Mocked Calibre fetch with fake EPUB files

## Common Patterns

### Testing API with Auth

```python
@pytest.mark.asyncio
async def test_authenticated_endpoint(client: AsyncClient, test_user: User):
    # Note: Current tests don't enforce auth, but real app does
    # For now, dependency overrides bypass auth in tests
    response = await client.get("/api/subscriptions")
    assert response.status_code == 200
```

### Testing Database State

```python
async def test_db_state_change(db_session: AsyncSession, test_subscription):
    # Modify data
    test_subscription.enabled = False
    await db_session.flush()

    # Refresh to get updated data
    await db_session.refresh(test_subscription)

    assert test_subscription.enabled is False
```

### Mocking External Services

```python
async def test_with_mock(mock_calibre_fetch, mock_smtp, tmp_path):
    # mock_calibre_fetch creates fake EPUBs
    # mock_smtp prevents actual email sending

    result = await delivery_engine.execute(...)

    # Verify mock was called
    mock_smtp.assert_called_once()
```

## Debugging Failed Tests

### Show full traceback

```bash
uv run pytest -v --tb=long
```

### Show local variables in traceback

```bash
uv run pytest -v --tb=long --showlocals
```

### Stop on first failure

```bash
uv run pytest -v -x
```

### Run last failed tests only

```bash
uv run pytest -v --lf
```

### Print statements in tests

```python
def test_something():
    print("Debug info:", some_value)  # Use -s flag to see output
    assert some_value == expected

# Run with: uv run pytest -v -s
```

## CI/CD

Tests run automatically on:
- Push to `main` branch
- Push to `claude/**` branches
- Pull requests to `main`

See `.github/workflows/test.yml` for configuration.

## Next Steps

See `TEST_PLAN.md` for detailed recommendations on:
- Priority 1: API endpoint tests (subscriptions, settings, deliveries)
- Priority 2: Auth flow tests (setup, login, password reset)
- Priority 3: Edge case tests (duplicate detection, data retention)

## Philosophy

> "Every test should answer: What bug does this prevent?"

Write tests that:
- ✅ Catch real regressions
- ✅ Validate critical functionality
- ✅ Run fast (< 1 second total)
- ❌ Don't test framework behavior
- ❌ Don't test external services (mock them)
- ❌ Don't test for 100% coverage

## Quick Wins

Add these high-value tests next:

1. **POST /api/subscriptions** - Create subscription via API
2. **PATCH /api/subscriptions/{id}** - Toggle subscription
3. **POST /api/subscriptions/{id}/force-send** - Force delivery
4. **POST /setup** - First user creation
5. **POST /api/auth/forgot-password** - Password reset flow
