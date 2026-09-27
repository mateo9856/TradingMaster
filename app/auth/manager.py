import logging
import re
import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, InvalidPasswordException, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from app.config import AUTH_RESET_SECRET, AUTH_VERIFY_SECRET
from app.models.user import User
from .db import get_user_db

logger = logging.getLogger(__name__)

# Password policy. fastapi-users' BaseUserManager.validate_password is a no-op,
# so until this existed "a" was an accepted password for an account that can
# reconfigure exchanges and insert prices.
MIN_PASSWORD_LENGTH = 12
# bcrypt-style backends truncate silently past ~72 bytes; reject rather than
# quietly ignore the tail, and cap the work an attacker can force per hash.
MAX_PASSWORD_LENGTH = 128

# A small set of passwords that meet the length rule but are still the first
# things tried. Not a substitute for a breach-corpus check (see the security
# audit's tracked items) — just the obvious ones.
COMMON_PASSWORDS = frozenset({
    "password1234", "passwordpassword", "123456789012", "qwertyuiopas",
    "administrator", "tradingmaster", "letmeinplease", "changeme1234",
})


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # Distinct keys per purpose: with one shared secret, a password-reset token
    # and a session token were signed by the same key.
    reset_password_token_secret = AUTH_RESET_SECRET
    verification_token_secret = AUTH_VERIFY_SECRET

    async def validate_password(self, password: str, user: User) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        if len(password) > MAX_PASSWORD_LENGTH:
            raise InvalidPasswordException(
                reason=f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
            )
        if password.lower() in COMMON_PASSWORDS:
            raise InvalidPasswordException(
                reason="That password is too common. Choose something less guessable."
            )

        email = getattr(user, "email", None) or ""
        if email:
            local_part = email.split("@")[0]
            if local_part and local_part.lower() in password.lower():
                raise InvalidPasswordException(
                    reason="Password must not contain your email address."
                )
        if password.lower() == email.lower():
            raise InvalidPasswordException(reason="Password must not be your email address.")

        # A single repeated character passes a length check but is trivially guessed.
        if re.fullmatch(r"(.)\1*", password):
            raise InvalidPasswordException(reason="Password must not be a single repeated character.")

    # These log the user id only. The email address used to be written in
    # plaintext to structured logs that ship to Loki, which put PII in a store
    # with a different retention and access model than the database.
    async def on_after_register(self, user: User, request: Optional[Request] = None):
        logger.info(f"User registered: {user.id}")

    async def on_after_forgot_password(self, user: User, token: str, request: Optional[Request] = None):
        # NOTE: no email backend is wired up, so this token is never delivered.
        # The token itself is deliberately not logged.
        logger.info(f"Password reset requested for user {user.id}")

    async def on_after_request_verify(self, user: User, token: str, request: Optional[Request] = None):
        logger.info(f"Verification requested for user {user.id}")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)
