import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUserOptional, DbSession, DeliveryEngineDep, get_current_user_optional
from app.models import Delivery, DeliveryStatus, Subscription, SubscriptionType
from app.services import CalibreError, calibre
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    authenticate_user,
    create_session_token,
    create_user,
    user_count,
)
from app.services.scheduler import calculate_next_run
from app.services.smtp import SMTPConfig, SMTPError, verify_smtp_connection


@dataclass
class HealthStats:
    """Subscription health statistics."""
    total: int
    active: int
    paused: int
    failing: int
    failing_subscriptions: list


@dataclass
class DailyStats:
    """Daily delivery statistics."""
    total_today: int
    successful_today: int
    failed_today: int
    skipped_today: int


@dataclass
class RecentDeliveryItem:
    """A recent delivery for display."""
    id: int
    name: str
    status: str
    completed_at: datetime | None
    error_message: str | None
    file_size_kb: float | None
    article_count: int | None
    subscription_id: int | None = None


@dataclass
class FailingSub:
    """A failing subscription."""
    id: int
    name: str
    consecutive_failures: int
    last_error: str | None

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def get_dashboard_data(db: DbSession, user_id: int):
    """Fetch all dashboard data for a user."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_24h = now + timedelta(hours=24)

    # Get all subscriptions
    all_subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    all_subs = all_subs_result.scalars().all()

    # Upcoming deliveries (next 24 hours)
    # Handle naive datetimes from SQLite by assuming UTC
    def make_aware(dt):
        if dt and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    upcoming = [
        s for s in all_subs
        if s.enabled and s.next_run_at and make_aware(s.next_run_at) <= next_24h
    ]
    upcoming.sort(key=lambda s: make_aware(s.next_run_at) or now)

    # Recent deliveries (last 10)
    recent_result = await db.execute(
        select(Delivery, Subscription.name)
        .join(Subscription, Delivery.subscription_id == Subscription.id, isouter=True)
        .where(Delivery.user_id == user_id)
        .order_by(desc(Delivery.created_at))
        .limit(10)
    )
    recent_rows = recent_result.all()
    recent = [
        RecentDeliveryItem(
            id=d.id,
            name=name or "Deleted",
            status=d.status.value if isinstance(d.status, DeliveryStatus) else d.status,
            completed_at=d.completed_at,
            error_message=d.error_message,
            file_size_kb=d.file_size_bytes / 1024 if d.file_size_bytes else None,
            article_count=d.article_count,
            subscription_id=d.subscription_id,
        )
        for d, name in recent_rows
    ]

    # Health stats - find failing subscriptions
    failing_subs: list[FailingSub] = []
    for sub in all_subs:
        last_deliveries_result = await db.execute(
            select(Delivery)
            .where(Delivery.subscription_id == sub.id)
            .order_by(desc(Delivery.created_at))
            .limit(3)
        )
        last_deliveries = last_deliveries_result.scalars().all()

        consecutive_failures = 0
        for delivery in last_deliveries:
            if delivery.status == DeliveryStatus.FAILED:
                consecutive_failures += 1
            else:
                break

        # Only show in "Needs Attention" if failures exist AND last_error is set
        # (dismiss clears last_error, hiding the alert)
        if consecutive_failures >= 2 and sub.last_error:
            failing_subs.append(FailingSub(
                id=sub.id,
                name=sub.name,
                consecutive_failures=consecutive_failures,
                last_error=sub.last_error,
            ))

    health = HealthStats(
        total=len(all_subs),
        active=sum(1 for s in all_subs if s.enabled),
        paused=sum(1 for s in all_subs if not s.enabled),
        failing=len(failing_subs),
        failing_subscriptions=failing_subs,
    )

    # Daily stats
    total_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user_id,
            Delivery.created_at >= today_start,
        )
    )
    successful_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user_id,
            Delivery.created_at >= today_start,
            Delivery.status == DeliveryStatus.SENT,
        )
    )
    failed_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user_id,
            Delivery.created_at >= today_start,
            Delivery.status == DeliveryStatus.FAILED,
        )
    )
    skipped_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user_id,
            Delivery.created_at >= today_start,
            Delivery.status == DeliveryStatus.SKIPPED,
        )
    )

    stats = DailyStats(
        total_today=total_today_result.scalar() or 0,
        successful_today=successful_today_result.scalar() or 0,
        failed_today=failed_today_result.scalar() or 0,
        skipped_today=skipped_today_result.scalar() or 0,
    )

    return all_subs, upcoming, recent, health, stats


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
):
    if not user:
        count = await user_count(db)
        if count == 0:
            return RedirectResponse(url="/setup", status_code=302)
        return RedirectResponse(url="/login", status_code=302)

    subscriptions, upcoming, recent, health, stats = await get_dashboard_data(db, user.id)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "subscriptions": subscriptions,
            "upcoming": upcoming,
            "recent": recent,
            "health": health,
            "stats": stats,
        },
    )


@router.get("/dashboard/upcoming", response_class=HTMLResponse)
async def dashboard_upcoming(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
):
    """htmx partial for upcoming deliveries widget."""
    if not user:
        return HTMLResponse("")

    now = datetime.now(timezone.utc)
    next_24h = now + timedelta(hours=24)

    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.enabled == True,
            Subscription.next_run_at != None,
            Subscription.next_run_at <= next_24h,
        )
        .order_by(Subscription.next_run_at)
    )
    upcoming = result.scalars().all()

    return templates.TemplateResponse(
        "components/upcoming_deliveries.html",
        {"request": request, "upcoming": upcoming},
    )


@router.get("/dashboard/recent", response_class=HTMLResponse)
async def dashboard_recent(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
):
    """htmx partial for recent activity widget."""
    if not user:
        return HTMLResponse("")

    result = await db.execute(
        select(Delivery, Subscription.name)
        .join(Subscription, Delivery.subscription_id == Subscription.id, isouter=True)
        .where(Delivery.user_id == user.id)
        .order_by(desc(Delivery.created_at))
        .limit(10)
    )
    recent_rows = result.all()
    recent = [
        RecentDeliveryItem(
            id=d.id,
            name=name or "Deleted",
            status=d.status.value if isinstance(d.status, DeliveryStatus) else d.status,
            completed_at=d.completed_at,
            error_message=d.error_message,
            file_size_kb=d.file_size_bytes / 1024 if d.file_size_bytes else None,
            article_count=d.article_count,
            subscription_id=d.subscription_id,
        )
        for d, name in recent_rows
    ]

    return templates.TemplateResponse(
        "components/recent_activity.html",
        {"request": request, "recent": recent},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: CurrentUserOptional,
):
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_submit(
    request: Request,
    response: Response,
    db: DbSession,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user = await authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    token = create_session_token(user.id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(key=SESSION_COOKIE_NAME)
    return resp


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(
    request: Request,
    db: DbSession,
):
    count = await user_count(db)
    if count > 0:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("setup.html", {"request": request})


@router.post("/setup")
async def setup_submit(
    request: Request,
    db: DbSession,
    username: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    count = await user_count(db)
    if count > 0:
        return RedirectResponse(url="/login", status_code=302)

    if len(password) < 8:
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Password must be at least 8 characters"},
            status_code=400,
        )

    user = await create_user(db, username, email, password)
    await db.commit()

    token = create_session_token(user.id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/recipes", response_class=HTMLResponse)
async def recipes_browser(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
    search: str | None = Query(None),
    letter: str | None = Query(None),
    page: int = Query(1, ge=1),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    page_size = 50
    recipes = []
    total = 0

    try:
        all_recipes = await calibre.list_builtin_recipes()

        filtered = all_recipes
        if search:
            search_lower = search.lower()
            filtered = [r for r in filtered if search_lower in r.title.lower()]
        if letter:
            if letter == "#":
                # Non-alphabetic (numbers, symbols)
                filtered = [r for r in filtered if r.title and not r.title[0].isalpha()]
            else:
                filtered = [r for r in filtered if r.title and r.title[0].upper() == letter.upper()]

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        recipes = filtered[start:end]
    except CalibreError:
        pass

    return templates.TemplateResponse(
        "recipes/browser.html",
        {
            "request": request,
            "user": user,
            "recipes": recipes,
            "total": total,
            "page": page,
            "page_size": page_size,
            "search": search,
            "letter": letter,
        },
    )


@router.get("/subscriptions/new", response_class=HTMLResponse)
async def subscription_new(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
    recipe: str | None = Query(None),
    title: str | None = Query(None),
    rss_url: str | None = Query(None),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "subscriptions/form.html",
        {
            "request": request,
            "user": user,
            "subscription": None,
            "recipe": recipe,
            "title": title,
            "rss_url": rss_url,
        },
    )


@router.post("/subscriptions/new")
async def subscription_create(
    request: Request,
    db: DbSession,
    user: Annotated[CurrentUserOptional, Depends(get_current_user_optional)],
    name: Annotated[str, Form()],
    type: Annotated[str, Form()],
    recipe: Annotated[str | None, Form()] = None,
    rss_url: Annotated[str | None, Form()] = None,
    schedule_type: Annotated[str, Form()] = "daily",
    schedule_time: Annotated[str, Form()] = "07:00",
    max_articles: Annotated[int, Form()] = 25,
    oldest_days: Annotated[int, Form()] = 7,
    include_images: Annotated[bool, Form()] = False,
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    source = recipe if type == "recipe" else rss_url
    if not source:
        return templates.TemplateResponse(
            "subscriptions/form.html",
            {
                "request": request,
                "user": user,
                "subscription": None,
                "error": "Please provide a recipe name or RSS URL",
            },
            status_code=400,
        )

    schedule_dict = {"type": schedule_type, "time": schedule_time}

    # Calculate initial next_run_at
    next_run = calculate_next_run(
        schedule=schedule_dict,
        timezone=user.timezone,
    )

    subscription = Subscription(
        user_id=user.id,
        type=SubscriptionType.RECIPE if type == "recipe" else SubscriptionType.RSS,
        source=source,
        name=name,
        schedule=schedule_dict,
        settings={
            "max_articles": max_articles,
            "oldest_days": oldest_days,
            "include_images": include_images,
        },
        next_run_at=next_run,
    )
    db.add(subscription)
    await db.commit()

    return RedirectResponse(url="/", status_code=302)


@router.get("/subscriptions/{subscription_id}/edit", response_class=HTMLResponse)
async def subscription_edit(
    request: Request,
    subscription_id: int,
    db: DbSession,
    user: CurrentUserOptional,
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "subscriptions/form.html",
        {
            "request": request,
            "user": user,
            "subscription": subscription,
        },
    )


@router.post("/subscriptions/{subscription_id}/edit")
async def subscription_update(
    request: Request,
    subscription_id: int,
    db: DbSession,
    user: Annotated[CurrentUserOptional, Depends(get_current_user_optional)],
    name: Annotated[str, Form()],
    schedule_type: Annotated[str, Form()] = "daily",
    schedule_time: Annotated[str, Form()] = "07:00",
    max_articles: Annotated[int, Form()] = 25,
    oldest_days: Annotated[int, Form()] = 7,
    include_images: Annotated[bool, Form()] = False,
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return RedirectResponse(url="/", status_code=302)

    subscription.name = name
    schedule_dict = {"type": schedule_type, "time": schedule_time}
    subscription.schedule = schedule_dict
    subscription.settings = {
        "max_articles": max_articles,
        "oldest_days": oldest_days,
        "include_images": include_images,
    }

    # Recalculate next_run_at when schedule changes
    subscription.next_run_at = calculate_next_run(
        schedule=schedule_dict,
        timezone=user.timezone,
        last_run_at=subscription.last_run_at,
        created_at=subscription.created_at,
    )

    await db.commit()

    return RedirectResponse(url="/", status_code=302)


@router.post("/subscriptions/{subscription_id}/delete")
async def subscription_delete(
    subscription_id: int,
    db: DbSession,
    user: Annotated[CurrentUserOptional, Depends(get_current_user_optional)],
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        await db.delete(subscription)
        await db.commit()

    return RedirectResponse(url="/", status_code=302)


@router.post("/subscriptions/{subscription_id}/send", response_class=HTMLResponse)
async def subscription_send(
    subscription_id: int,
    db: DbSession,
    user: Annotated[CurrentUserOptional, Depends(get_current_user_optional)],
    engine: DeliveryEngineDep,
):
    """Send a subscription now and return HTML snippet for htmx."""
    if not user:
        return "<span class='text-red-600'>Not logged in</span>"

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        return "<span class='text-red-600'>Not found</span>"

    if not user.kindle_email:
        return "<span class='text-red-600'>Set Kindle email first</span>"

    if not user.smtp_config:
        return "<span class='text-red-600'>Configure SMTP first</span>"

    try:
        delivery_result = await engine.execute(
            db=db,
            subscription=subscription,
            user=user,
        )

        if delivery_result.status == DeliveryStatus.SENT:
            return "<span class='text-green-600'>Sent!</span>"
        elif delivery_result.status == DeliveryStatus.SKIPPED:
            return "<span class='text-yellow-600'>Skipped (already sent today)</span>"
        else:
            # Show full error since result now has its own row
            error = delivery_result.error_message or "Unknown error"
            return f"<span class='text-red-600'>Failed: {html.escape(error)}</span>"

    except Exception as e:
        return f"<span class='text-red-600'>Error: {html.escape(str(e))}</span>"


@router.post("/subscriptions/{subscription_id}/force-send", response_class=HTMLResponse)
async def subscription_force_send(
    subscription_id: int,
    db: DbSession,
    user: Annotated[CurrentUserOptional, Depends(get_current_user_optional)],
    engine: DeliveryEngineDep,
):
    """Force send a subscription, bypassing same-day duplicate check."""
    if not user:
        return "<span class='text-red-600'>Not logged in</span>"

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        return "<span class='text-red-600'>Not found</span>"

    if not user.kindle_email:
        return "<span class='text-red-600'>Set Kindle email first</span>"

    if not user.smtp_config:
        return "<span class='text-red-600'>Configure SMTP first</span>"

    try:
        delivery_result = await engine.execute(
            db=db,
            subscription=subscription,
            user=user,
            force=True,  # Skip duplicate check
        )

        if delivery_result.status == DeliveryStatus.SENT:
            return "<span class='text-green-600'>Sent!</span>"
        else:
            error = delivery_result.error_message or "Unknown error"
            return f"<span class='text-red-600'>Failed: {html.escape(error)}</span>"

    except Exception as e:
        return f"<span class='text-red-600'>Error: {html.escape(str(e))}</span>"


# Settings routes


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
    success: str | None = Query(None),
    error: str | None = Query(None),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    smtp = user.smtp_config or {}

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "smtp": smtp,
            "success": success,
            "error": error,
        },
    )


@router.post("/settings")
async def settings_update(
    request: Request,
    db: DbSession,
    user: Annotated[CurrentUserOptional, Depends(get_current_user_optional)],
    section: Annotated[str, Form()],
    kindle_email: Annotated[str | None, Form()] = None,
    smtp_host: Annotated[str | None, Form()] = None,
    smtp_port: Annotated[int, Form()] = 587,
    smtp_username: Annotated[str | None, Form()] = None,
    smtp_password: Annotated[str | None, Form()] = None,
    smtp_from_email: Annotated[str | None, Form()] = None,
    smtp_use_tls: Annotated[bool, Form()] = False,
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if section == "kindle":
        user.kindle_email = kindle_email
        await db.commit()
        return RedirectResponse(url="/settings?success=Kindle+email+saved", status_code=302)

    elif section == "smtp":
        # Keep existing password if not provided
        existing_smtp = user.smtp_config or {}
        password = smtp_password if smtp_password else existing_smtp.get("password")

        if not password and not existing_smtp.get("password"):
            return RedirectResponse(
                url="/settings?error=Password+is+required", status_code=302
            )

        user.smtp_config = {
            "host": smtp_host,
            "port": smtp_port,
            "username": smtp_username,
            "password": password,
            "from_email": smtp_from_email,
            "use_tls": smtp_use_tls,
        }
        await db.commit()
        return RedirectResponse(url="/settings?success=SMTP+settings+saved", status_code=302)

    return RedirectResponse(url="/settings", status_code=302)


@router.post("/settings/test-smtp", response_class=HTMLResponse)
async def settings_test_smtp(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
):
    if not user:
        return HTMLResponse('<span class="text-red-600">Not authenticated</span>')

    if not user.smtp_config:
        return HTMLResponse('<span class="text-red-600">SMTP not configured</span>')

    try:
        config = SMTPConfig.from_dict(user.smtp_config)
        await verify_smtp_connection(config)
        return HTMLResponse(
            f'<span class="text-green-600">Connected successfully to {config.host}:{config.port}</span>'
        )
    except SMTPError as e:
        return HTMLResponse(f'<span class="text-red-600">{e}</span>')


# History route


@router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    db: DbSession,
    user: CurrentUserOptional,
    page: int = Query(1, ge=1),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    page_size = 20

    result = await db.execute(
        select(Delivery)
        .options(selectinload(Delivery.subscription))
        .where(Delivery.user_id == user.id)
        .order_by(Delivery.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)  # Fetch one extra to check if there's more
    )
    deliveries = list(result.scalars().all())

    has_more = len(deliveries) > page_size
    if has_more:
        deliveries = deliveries[:page_size]

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "user": user,
            "deliveries": deliveries,
            "page": page,
            "has_more": has_more,
        },
    )
