from secrets import token_hex

from fastapi import Depends, Response
from pydantic import BaseModel, Field

from ..auth import internal, owned, staff, user
from ..database import Database
from ..http_app import app_for, error
from ..service_client import CircuitBreaker, call
from ..values import now

DB = Database("groups")
SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
 id AUTO_ID, teacher BIGINT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
 invite_code TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memberships (
 id AUTO_ID, group_id BIGINT NOT NULL REFERENCES groups(id), student BIGINT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(group_id, student)
);
CREATE INDEX IF NOT EXISTS memberships_student ON memberships(student);
"""
app = app_for("РепИТ · Учебные группы", DB, SCHEMA)
identity_breaker = CircuitBreaker()


class GroupInput(BaseModel):
    title: str | None = Field(default=None, max_length=150)
    name: str | None = Field(default=None, max_length=150)
    description: str = Field(default="", max_length=10000)


class GroupKey(BaseModel):
    group: int


class Invite(BaseModel):
    invite_code: str = Field(max_length=50)


class MemberInput(GroupKey):
    student: int


def visible_group(db, key, actor):
    group = db.get("groups", key)
    if group["deleted"]:
        error(404, "Группа не найдена.")
    if actor["role"] == "student":
        if not db.one("SELECT id FROM memberships WHERE group_id = ? AND student = ?", (key, actor["id"])):
            error(404, "Группа не найдена.")
    else:
        owned(group, actor, "teacher")
    return group


def group_view(db, group, actor):
    count = db.one("SELECT COUNT(*) AS n FROM memberships WHERE group_id = ?", (group["id"],))["n"]
    result = {key: value for key, value in group.items() if key != "deleted"}
    if actor["role"] == "student":
        result["invite_code"] = ""
    return {**result, "members_count": count, "students_count": count}


def member_view(member, group, account):
    return {"id": member["id"], "group": group["id"], "group_title": group["title"], "student": member["student"],
            "student_email": account["email"], "student_first_name": account["first_name"],
            "student_last_name": account["last_name"], "joined_at": member["created_at"],
            "created_at": member["created_at"]}


def get_student(key):
    account = call("identity", f"/internal/users/{key}", retries=1, breaker=identity_breaker)
    if account["role"] != "student" or not account["is_active"] or account["is_blocked"]:
        error(400, "Нужен активный аккаунт учащегося.")
    return account


@app.get("/api/groups/")
def list_groups(actor=Depends(user)):
    with DB.connect() as db:
        if actor["role"] == "teacher":
            groups = db.all("SELECT * FROM groups WHERE deleted = 0 AND teacher = ? ORDER BY id DESC", (actor["id"],))
        elif actor["role"] == "student":
            groups = db.all("SELECT g.* FROM groups g JOIN memberships m ON m.group_id = g.id "
                            "WHERE g.deleted = 0 AND m.student = ? ORDER BY g.id DESC", (actor["id"],))
        else:
            groups = db.all("SELECT * FROM groups WHERE deleted = 0 ORDER BY id DESC")
        return [group_view(db, group, actor) for group in groups]


@app.post("/api/groups/", status_code=201)
def create_group(body: GroupInput, actor=Depends(user)):
    staff(actor)
    title = (body.title or body.name or "").strip()
    if not title:
        error(400, {"title": ["Укажите название группы."]})
    with DB.connect(write=True) as db:
        group = db.insert("groups", {"title": title, "description": body.description, "teacher": actor["id"],
                                     "invite_code": token_hex(6).upper(), "created_at": now()})
        return group_view(db, group, actor)


@app.post("/api/groups/join/")
def join(body: Invite, response: Response, actor=Depends(user)):
    if actor["role"] != "student":
        error(403, "Вступать по коду может учащийся.")
    account = get_student(actor["id"])
    with DB.connect(write=True) as db:
        group = db.one("SELECT * FROM groups WHERE deleted = 0 AND invite_code = ?",
                       (body.invite_code.strip().upper(),), lock=True)
        if not group:
            error(404, "Группа не найдена.")
        member, created = ensure_member(db, group["id"], actor["id"])
        response.status_code = 201 if created else 200
        return member_view(member, group, account)


@app.get("/api/groups/{group_id}/")
def group_detail(group_id: int, actor=Depends(user)):
    with DB.connect() as db:
        return group_view(db, visible_group(db, group_id, actor), actor)


@app.patch("/api/groups/{group_id}/")
@app.put("/api/groups/{group_id}/")
def update_group(group_id: int, body: GroupInput, actor=Depends(user)):
    staff(actor)
    with DB.connect(write=True) as db:
        visible_group(db, group_id, actor)
        fields = body.model_dump(exclude_unset=True, exclude={"name"})
        if "title" in fields or body.name is not None:
            fields["title"] = (body.title or body.name or "").strip()
            if not fields["title"]:
                error(400, {"title": ["Укажите название группы."]})
        if fields:
            db.update("groups", group_id, fields)
        return group_view(db, visible_group(db, group_id, actor), actor)


@app.delete("/api/groups/{group_id}/", status_code=204)
def delete_group(group_id: int, actor=Depends(user)):
    staff(actor)
    with DB.connect(write=True) as db:
        visible_group(db, group_id, actor)
        db.update("groups", group_id, {"deleted": 1})


@app.post("/api/groups/{group_id}/regenerate-code/")
def regenerate(group_id: int, actor=Depends(user)):
    staff(actor)
    with DB.connect(write=True) as db:
        visible_group(db, group_id, actor)
        code = token_hex(6).upper()
        db.update("groups", group_id, {"invite_code": code})
    return {"invite_code": code}


def ensure_member(db, group_id, student):
    fields = (group_id, student)
    member = db.one("INSERT INTO memberships (group_id, student, created_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (group_id, student) DO NOTHING RETURNING *", (*fields, now()))
    if member:
        return member, True
    return db.one("SELECT * FROM memberships WHERE group_id = ? AND student = ?", fields), False


@app.get("/api/group-memberships/")
def list_memberships(group: int | None = None, student: int | None = None, actor=Depends(user)):
    filters = ["g.deleted = 0"]
    values = []
    for condition, value in (
        ("g.teacher = ?", actor["id"] if actor["role"] == "teacher" else None),
        ("m.student = ?", actor["id"] if actor["role"] == "student" else None),
        ("m.group_id = ?", group), ("m.student = ?", student),
    ):
        if value is not None:
            filters.append(condition)
            values.append(value)
    with DB.connect() as db:
        records = db.all("SELECT m.*, g.title FROM memberships m JOIN groups g ON g.id = m.group_id WHERE "
                         + " AND ".join(filters) + " ORDER BY m.id DESC", values)
    if not records:
        return []
    accounts = {item["id"]: item for item in call("identity", "/internal/users-batch",
                method="POST", body=sorted({item["student"] for item in records}))}
    return [member_view(item, {"id": item["group_id"], "title": item["title"]},
                        accounts.get(item["student"], {"email": "", "first_name": "", "last_name": ""}))
            for item in records]


@app.post("/api/group-memberships/", status_code=201)
def add_member(body: MemberInput, actor=Depends(user)):
    staff(actor)
    account = get_student(body.student)
    with DB.connect(write=True) as db:
        group = visible_group(db, body.group, actor)
        member, _ = ensure_member(db, body.group, body.student)
        return member_view(member, group, account)


@app.get("/api/group-memberships/{member_id}/")
def membership_detail(member_id: int, actor=Depends(user)):
    with DB.connect() as db:
        member = db.get("memberships", member_id)
        group = visible_group(db, member["group_id"], actor)
    if actor["role"] == "student" and actor["id"] != member["student"]:
        error(403, "Нет доступа.")
    account = call("identity", f"/internal/users/{member['student']}")
    return member_view(member, group, account)


@app.delete("/api/group-memberships/{member_id}/", status_code=204)
def remove_member(member_id: int, actor=Depends(user)):
    with DB.connect(write=True) as db:
        member = db.get("memberships", member_id)
        visible_group(db, member["group_id"], actor)
        if actor["role"] == "student" and actor["id"] != member["student"]:
            error(403, "Нет доступа.")
        db.execute("DELETE FROM memberships WHERE id = ?", (member_id,))


@app.post("/api/group-memberships/leave/", status_code=204)
def leave(body: GroupKey, actor=Depends(user)):
    with DB.connect(write=True) as db:
        result = db.execute("DELETE FROM memberships WHERE group_id = ? AND student = ?", (body.group, actor["id"]))
        if not result.rowcount:
            error(400, "Вы не состоите в группе.")


@app.get("/internal/teachers/{teacher}/students/", dependencies=[Depends(internal)])
def teacher_students(teacher: int):
    with DB.connect() as db:
        records = db.all("SELECT DISTINCT m.student FROM memberships m JOIN groups g ON g.id = m.group_id "
                         "WHERE g.teacher = ? AND g.deleted = 0", (teacher,))
    return [row["student"] for row in records]


@app.get("/internal/students/{student}/groups/", dependencies=[Depends(internal)])
def student_groups(student: int):
    with DB.connect() as db:
        records = db.all("SELECT m.group_id FROM memberships m JOIN groups g ON g.id = m.group_id "
                         "WHERE m.student = ? AND g.deleted = 0", (student,))
    return [row["group_id"] for row in records]


@app.get("/internal/teachers/{teacher}/groups/", dependencies=[Depends(internal)])
def teacher_groups(teacher: int, admin: bool = False):
    with DB.connect() as db:
        query = "SELECT id, title, teacher FROM groups WHERE deleted = 0"
        return db.all(query if admin else query + " AND teacher = ?", () if admin else (teacher,))


@app.post("/internal/groups/students/", dependencies=[Depends(internal)])
def group_students(keys: list[int]):
    if not keys:
        return []
    with DB.connect() as db:
        query = "SELECT DISTINCT m.student FROM memberships m JOIN groups g ON g.id = m.group_id WHERE g.deleted = 0"
        return [row["student"] for row in db.all(query + " AND m.group_id IN (" + ",".join("?" for _ in keys) + ")", keys)]
