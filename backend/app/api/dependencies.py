import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database.models import User
from app.database.session import get_db
from app.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    claims = decode_access_token(token)
    if claims is None:
        raise unauthorized
    try:
        user = db.get(User, uuid.UUID(str(claims["sub"])))
    except ValueError:
        raise unauthorized from None
    if user is None or claims.get("tv") != user.token_version:
        raise unauthorized
    return user
