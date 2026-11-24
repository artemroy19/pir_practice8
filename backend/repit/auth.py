import hmac
import os
import time

import jwt
from fastapi import Header

from .http_app import error

JWT_SECRET = os.getenv("SECRET_KEY", "repit-local-only-change-this-secret-key")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "repit-local-internal")

def token(user, purpose, lifetime):
    return jwt.encode({"sub": str(user["id"]), "role": user["role"], "kind": purpose,
                       "ver": user.get("token_version", 0), "exp": int(time.time()) + lifetime},
                      JWT_SECRET, algorithm="HS256")


def decode(raw, purpose):
    try:
        claims = jwt.decode(raw, JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub", "kind"]})
        if claims["kind"] == purpose:
            return {"id": int(claims["sub"]), "role": claims["role"], "token_version": claims["ver"]}
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        pass
    error(401, "Токен недействителен или истёк.")


def user(authorization: str = Header(default="")):
    return decode(authorization.removeprefix("Bearer "), "access")


def internal(x_internal_key: str = Header(default="")):
    if not hmac.compare_digest(x_internal_key, INTERNAL_KEY):
        error(403, "Внутренний маршрут.")


def staff(actor):
    if actor["role"] not in {"teacher", "admin"}:
        error(403, "Доступно преподавателю.")


def owned(record, actor, field="owner"):
    if actor["role"] != "admin" and record[field] != actor["id"]:
        error(403, "Нет доступа к этой записи.")
