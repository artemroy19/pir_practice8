import base64
import hashlib
import hmac
import io
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Depends, Request
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from ..auth import decode, internal, token, user
from ..database import Database
from ..http_app import app_for, error
from ..service_client import call
from ..values import now

DB = Database("identity")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id AUTO_ID, email TEXT UNIQUE NOT NULL, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
 first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '', avatar TEXT,
 role TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, is_blocked INTEGER NOT NULL DEFAULT 0,
 token_version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
"""
app = app_for("РепИТ · Аккаунты", DB, SCHEMA)
MEDIA = Path(os.getenv("MEDIA_DIR", "/tmp/repit-media"))
app.mount("/media", StaticFiles(directory=MEDIA, check_dir=False), name="media")
PUBLIC_FIELDS = ("id", "email", "username", "first_name", "last_name", "avatar", "role",
                 "is_active", "is_blocked", "created_at")


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class Register(Login):
    name: str = Field(default="", max_length=150)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)
    username: str = Field(default="", max_length=150)
    role: Literal["student", "teacher"]


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ResetRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetConfirm(BaseModel):
    uid: str
    token: str
    new_password: str = Field(min_length=8, max_length=256)


class Refresh(BaseModel):
    refresh: str


def password_hash(password):
    salt = uuid4().hex
    return f"pbkdf2_sha256$1000000${salt}$" + digest(password, salt, 1000000)


def digest(password, salt, iterations):
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return base64.b64encode(value).decode()


def valid_password(password, encoded):
    algorithm, iterations, salt, expected = encoded.split("$", 3)
    return algorithm == "pbkdf2_sha256" and hmac.compare_digest(digest(password, salt, iterations), expected)


def public(account):
    data = {field: account[field] for field in PUBLIC_FIELDS}
    data["is_active"] = bool(data["is_active"])
    data["is_blocked"] = bool(data["is_blocked"])
    return data


def tokens(account):
    return {"access": token(account, "access", 1800), "refresh": token(account, "refresh", 604800),
            "user": public(account)}


def create_account(body):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        error(400, {"email": ["Укажите корректный адрес."]})
    if len(body.password) < 8 or body.password.isdecimal():
        error(400, {"password": ["Пароль должен содержать не менее 8 символов и не состоять только из цифр."]})
    base = "".join(char for char in (body.username or body.name or email.split("@")[0]).lower()
                   if char.isalnum())[:28] or "user"
    with DB.connect(write=True) as db:
        if db.postgres:
            db.execute("SELECT pg_advisory_xact_lock(10478)")
        if db.one("SELECT id FROM users WHERE email = ?", (email,)):
            error(400, {"email": ["Пользователь с таким адресом уже существует."]})
        username = base
        counter = 1
        while db.one("SELECT id FROM users WHERE username = ?", (username,)):
            username = f"{base}{counter}"
            counter += 1
        return db.insert("users", {"email": email, "username": username, "password": password_hash(body.password),
                                   "first_name": body.first_name or body.name, "last_name": body.last_name,
                                   "role": body.role, "created_at": now()})


@app.post("/api/auth/register/", status_code=201)
def register(body: Register):
    return tokens(create_account(body))


@app.post("/api/auth/login/")
def login(body: Login):
    with DB.connect() as db:
        account = db.one("SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),))
    dummy = "pbkdf2_sha256$1000000$repit$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    valid = valid_password(body.password, account["password"] if account else dummy)
    if not account or not valid or not account["is_active"] or account["is_blocked"]:
        error(401, "Неверные данные или аккаунт недоступен.")
    return tokens(account)


@app.post("/api/auth/refresh/")
def refresh(body: Refresh):
    actor = decode(body.refresh, "refresh")
    with DB.connect() as db:
        account = db.get("users", actor["id"])
    if not account["is_active"] or account["is_blocked"] or account["token_version"] != actor["token_version"]:
        error(401, "Сессия завершена.")
    return {"access": token(account, "access", 1800), "refresh": token(account, "refresh", 604800)}


@app.get("/api/me/")
@app.get("/api/auth/profile/")
def me(actor=Depends(user)):
    with DB.connect() as db:
        return public(db.get("users", actor["id"]))


@app.patch("/api/auth/profile/")
@app.put("/api/auth/profile/")
async def profile(request: Request, actor=Depends(user)):
    multipart = "multipart/form-data" in request.headers.get("content-type", "")
    values = await request.form() if multipart else await request.json()
    changes = {}
    for field in ("first_name", "last_name"):
        if field in values:
            value = values[field]
            if not isinstance(value, str) or len(value) > 150:
                error(400, {field: ["Некорректное значение."]})
            changes[field] = value.strip()
    if "avatar_file" in values:
        avatar = values["avatar_file"]
        if avatar is None:
            changes["avatar"] = None
        elif multipart and hasattr(avatar, "read"):
            raw = await avatar.read(5_000_001)
            if len(raw) > 5_000_000:
                error(400, {"avatar_file": ["Размер файла превышает 5 МБ."]})
            try:
                image = Image.open(io.BytesIO(raw))
                if image.width * image.height > 16_000_000:
                    error(400, {"avatar_file": ["Слишком большое изображение."]})
                image.thumbnail((512, 512))
                MEDIA.mkdir(parents=True, exist_ok=True)
                filename = f"{uuid4().hex}.png"
                image.convert("RGBA").save(MEDIA / filename)
                changes["avatar"] = "/media/" + filename
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
                error(400, {"avatar_file": ["Загрузите изображение."]})
        else:
            error(400, {"avatar_file": ["Загрузите изображение."]})
    with DB.connect(write=True) as db:
        account = db.get("users", actor["id"], lock=True)
        if not changes:
            return public(account)
        updated = db.update("users", actor["id"], changes)
    if "avatar" in changes and account["avatar"]:
        (MEDIA / Path(account["avatar"]).name).unlink(missing_ok=True)
    return public(updated)


@app.post("/api/auth/change-password/")
@app.post("/api/auth/password/change/")
def change_password(body: PasswordChange, actor=Depends(user)):
    with DB.connect(write=True) as db:
        account = db.get("users", actor["id"], lock=True)
        if not valid_password(body.old_password, account["password"]):
            error(400, {"old_password": ["Неверный текущий пароль."]})
        db.update("users", actor["id"], {"password": password_hash(body.new_password),
                                         "token_version": account["token_version"] + 1})
    return {"detail": "Пароль обновлён."}


@app.post("/api/auth/password-reset/request/")
def reset_request(body: ResetRequest):
    with DB.connect() as db:
        account = db.one("SELECT * FROM users WHERE email = ? AND is_active = 1 AND is_blocked = 0",
                         (body.email.strip().lower(),))
    if account and os.getenv("SMTP_HOST"):
        secret = token(account, "reset", 1800)
        message = EmailMessage()
        message["To"] = account["email"]
        message["From"] = os.getenv("SMTP_FROM", "noreply@repit.local")
        message["Subject"] = "РепИТ: восстановление пароля"
        query = urlencode({"uid": account["id"], "token": secret})
        site = os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/")
        message.set_content(f"Ссылка для сброса пароля:\n{site}/reset-password?{query}")
        try:
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "25")), timeout=3) as smtp:
                smtp.send_message(message)
        except OSError:
            logging.getLogger("repit").warning("SMTP недоступен")
    return {"detail": "Если email существует, инструкция отправлена."}


@app.post("/api/auth/password-reset/confirm/")
def reset_confirm(body: ResetConfirm):
    actor = decode(body.token, "reset")
    if str(actor["id"]) != body.uid:
        error(400, "Некорректный uid.")
    with DB.connect(write=True) as db:
        account = db.get("users", actor["id"], lock=True)
        if actor["token_version"] != account["token_version"] or account["is_blocked"] or not account["is_active"]:
            error(400, "Токен больше не действителен.")
        db.update("users", actor["id"], {"password": password_hash(body.new_password),
                                         "token_version": account["token_version"] + 1})
    return {"detail": "Пароль обновлён."}


@app.get("/internal/users/{user_id}", dependencies=[Depends(internal)])
def lookup_user(user_id: int):
    with DB.connect() as db:
        return public(db.get("users", user_id))


@app.get("/api/users/")
def list_users(ids: str = "", role: str = "", actor=Depends(user)):
    requested = {int(value) for value in ids.split(",") if value.isdigit()}
    allowed = None
    if actor["role"] == "teacher" and role != "student":
        allowed = set(call("groups", f"/internal/teachers/{actor['id']}/students/")) if ids else {actor["id"]}
    elif actor["role"] == "student":
        allowed = {actor["id"]}
    with DB.connect() as db:
        accounts = db.all("SELECT * FROM users ORDER BY id DESC")
    return [public(account) for account in accounts
            if (not ids or account["id"] in requested) and (not role or account["role"] == role)
            and (allowed is None or account["id"] in allowed)]


@app.get("/api/users/{user_id}/")
def get_user(user_id: int, actor=Depends(user)):
    matches = list_users(ids=str(user_id), actor=actor)
    if not matches:
        error(404, "Пользователь не найден.")
    return matches[0]


@app.post("/internal/users-batch", dependencies=[Depends(internal)])
def lookup_users(keys: list[int]):
    if not keys:
        return []
    with DB.connect() as db:
        sql = "SELECT * FROM users WHERE id IN (" + ",".join("?" for _ in keys) + ")"
        return [public(account) for account in db.all(sql, keys)]


@app.get("/internal/students/", dependencies=[Depends(internal)])
def active_students():
    with DB.connect() as db:
        return [public(account) for account in db.all(
            "SELECT * FROM users WHERE role = 'student' AND is_active = 1 AND is_blocked = 0 ORDER BY email")]
