import inspect

from fastapi import Depends, HTTPException, Request, status
from fastapi_login import LoginManager
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User

settings = get_settings()
manager = LoginManager(settings.auth_secret, token_url="/login", use_cookie=True)
manager.cookie_name = "yscoop_session"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


@manager.user_loader()
def load_user(username: str):
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))


async def require_user(request: Request) -> User:
    try:
        return await manager(request)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required") from exc


async def require_admin(current_user: User = Depends(require_user)) -> User:
    if inspect.isawaitable(current_user):
        current_user = await current_user
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
