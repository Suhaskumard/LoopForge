from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config import settings
from app.database.models import User
from app.database.session import get_db
from app.schemas.user import RefreshRequest, Token, UserCreate, UserOut
from app.services import auth_service
from app.utils.client_ip import client_ip
from app.utils.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(user: User, refresh_token: str) -> Token:
    return Token(
        access_token=create_access_token(str(user.id), user.token_version),
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)) -> User:
    email = data.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    return user


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    email = form.username.lower()
    key = f"{client_ip(request)}|{email}"
    if auth_service.is_login_blocked(db, key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts; try again later",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None or not verify_password(form.password, user.password_hash):
        auth_service.record_login_failure(db, key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    auth_service.clear_login_failures(db, key)
    return _token_pair(user, auth_service.start_session(db, user))


@router.post("/refresh", response_model=Token)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> Token:
    try:
        user, new_token = auth_service.rotate(db, body.refresh_token)
    except auth_service.InvalidRefreshToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None
    return _token_pair(user, new_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: Session = Depends(get_db)) -> Response:
    auth_service.revoke(db, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    auth_service.revoke_all(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
