from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr

from app.dependencies import CurrentUser, DbSession, require_setup_incomplete
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    authenticate_user,
    create_session_token,
    create_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    kindle_email: str | None
    timezone: str


@router.post("/login")
async def login(
    request: LoginRequest,
    response: Response,
    db: DbSession,
) -> dict:
    user = await authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )

    return {"message": "Login successful", "user_id": user.id}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"message": "Logged out"}


@router.get("/me")
async def get_current_user_info(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/setup")
async def setup_first_user(
    request: SetupRequest,
    response: Response,
    db: DbSession,
    _: Annotated[None, Depends(require_setup_incomplete)],
) -> dict:
    user = await create_user(db, request.username, request.email, request.password)
    await db.commit()

    token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )

    return {"message": "Setup complete", "user_id": user.id}
