import hmac

from fastapi import Request

from . import config


def is_admin(request: Request) -> bool:
    if config.ADMIN_AUTH_DISABLED:
        return True
    return bool(request.session.get("is_admin"))


def check_password(password: str) -> bool:
    return hmac.compare_digest(password, config.ADMIN_PASSWORD)
