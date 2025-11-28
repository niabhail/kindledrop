from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUserOptional, DbSession, get_current_user_optional
from app.models import Delivery, Subscription, SubscriptionType
from app.services import calibre, CalibreError
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    authenticate_user,
    create_session_token,
    create_user,
    user_count,
)
from app.services.smtp import SMTPConfig, SMTPError, verify_smtp_connection

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscriptions = result.scalars().all()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "subscriptions": subscriptions,
        },
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
    language: str | None = Query(None),
    page: int = Query(1, ge=1),
):
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    page_size = 20
    recipes = []
    total = 0

    try:
        all_recipes = await calibre.list_builtin_recipes()

        filtered = all_recipes
        if search:
            search_lower = search.lower()
            filtered = [r for r in filtered if search_lower in r.title.lower()]
        if language:
            filtered = [r for r in filtered if r.language == language.lower()]

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
            "language": language,
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

    subscription = Subscription(
        user_id=user.id,
        type=SubscriptionType.RECIPE if type == "recipe" else SubscriptionType.RSS,
        source=source,
        name=name,
        schedule={"type": schedule_type, "time": schedule_time},
        settings={
            "max_articles": max_articles,
            "oldest_days": oldest_days,
            "include_images": include_images,
        },
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
    subscription.schedule = {"type": schedule_type, "time": schedule_time}
    subscription.settings = {
        "max_articles": max_articles,
        "oldest_days": oldest_days,
        "include_images": include_images,
    }
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
