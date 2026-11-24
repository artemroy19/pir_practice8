import asyncio
import json
from hashlib import sha256
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth import internal, owned, staff, user
from ..database import Database
from ..http_app import app_for, error
from ..question_data import QuestionPrompt, QuestionTitle, QuestionType, format_points, student_payload
from ..service_client import CircuitBreaker, call
from ..values import document, now, parse_time
from .question_generation import Draft, GenerationInput, generate_draft
from .test_generation import GeneratedTest, TestGenerationInput, generate_test

DB = Database("catalog")
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
 id AUTO_ID, owner BIGINT NOT NULL, parent BIGINT REFERENCES categories(id) ON DELETE CASCADE,
 title TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
 id AUTO_ID, owner BIGINT NOT NULL, category_id BIGINT REFERENCES categories(id) ON DELETE SET NULL,
 title TEXT NOT NULL, prompt TEXT NOT NULL, question_type TEXT NOT NULL, base_points TEXT NOT NULL,
 payload TEXT NOT NULL, is_bank_question INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tests (
 id AUTO_ID, owner BIGINT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
 timer_minutes INTEGER, attempts_limit INTEGER, deadline TEXT, result_visibility TEXT NOT NULL,
 is_frozen INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_questions (
 id AUTO_ID, test BIGINT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 question BIGINT NOT NULL REFERENCES questions(id), position INTEGER NOT NULL, overridden_points TEXT,
 created_at TEXT NOT NULL, UNIQUE(test, question)
);
CREATE TABLE IF NOT EXISTS test_save_requests (
 owner BIGINT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 result TEXT NOT NULL, PRIMARY KEY (owner, request_key)
);
CREATE TABLE IF NOT EXISTS assignments (
 id AUTO_ID, test BIGINT NOT NULL REFERENCES tests(id) ON DELETE CASCADE, group_id BIGINT,
 student BIGINT, assigned_by BIGINT NOT NULL, created_at TEXT NOT NULL,
 CHECK ((group_id IS NULL) <> (student IS NULL)), UNIQUE(test, group_id), UNIQUE(test, student)
);
CREATE TABLE IF NOT EXISTS attempt_updates (
 id AUTO_ID, event_id TEXT NOT NULL UNIQUE, attempt BIGINT NOT NULL,
 test_id BIGINT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL, UNIQUE(attempt, revision)
);
CREATE INDEX IF NOT EXISTS attempt_updates_attempt ON attempt_updates(test_id, id);
"""
app = app_for("РепИТ · Вопросы, тесты и назначения", DB, SCHEMA)
group_breaker = CircuitBreaker()
attempts_breaker = CircuitBreaker()


class Category(BaseModel):
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=10000)
    parent: int | None = None


class Question(BaseModel):
    category_id: int | None = None
    title: QuestionTitle = ""
    prompt: QuestionPrompt = ""
    question_type: QuestionType = "single"
    base_points: Decimal = Field(default=1, ge=0, max_digits=6, decimal_places=2)
    payload: dict = Field(default_factory=dict)
    is_bank_question: bool = True


class TestInput(BaseModel):
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=10000)
    timer_minutes: int | None = Field(default=None, ge=0)
    attempts_limit: int | None = Field(default=None, ge=0)
    deadline: datetime | None = None
    result_visibility: Literal["score_only", "score_with_review"] = "score_only"


class DraftQuestionInput(Question):
    id: int | None = Field(default=None, gt=0)
    expected_updated_at: str | None = None
    overridden_points: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)


class DraftTestInput(BaseModel):
    test: TestInput
    test_id: int | None = Field(default=None, gt=0)
    expected_updated_at: str | None = None
    questions: list[DraftQuestionInput] = Field(min_length=1, max_length=1000)


class ItemInput(BaseModel):
    question: int
    order: int | None = Field(default=None, ge=1)
    overridden_points: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)


class RemoveInput(BaseModel):
    question: int | None = None
    test_question: int | None = None


class OrderInput(BaseModel):
    order: list[int]


class AssignmentInput(BaseModel):
    group_ids: list[int] = Field(default_factory=list, max_length=1000)
    student_ids: list[int] = Field(default_factory=list, max_length=1000)


class SingleAssignment(BaseModel):
    test: int
    group: int | None = None
    student: int | None = None


class Start(BaseModel):
    student: int


def title_required(data):
    if not data.get("title", "").strip():
        error(400, {"title": ["Укажите название."]})


def author_records(db, table, actor, *, condition="1 = 1"):
    staff(actor)
    if actor["role"] == "admin":
        return db.all(f"SELECT * FROM {table} WHERE {condition} ORDER BY id DESC")
    return db.all(f"SELECT * FROM {table} WHERE {condition} AND owner = ? ORDER BY id DESC", (actor["id"],))


def category_values(db, key, data, actor):
    title_required(data)
    if data["parent"] is not None:
        parent = db.get("categories", data["parent"])
        owned(parent, actor)
        if parent["parent"] is not None or parent["id"] == key:
            error(400, {"parent": ["Допустимо два уровня категорий."]})
        if key and db.one("SELECT id FROM categories WHERE parent = ?", (key,)):
            error(400, {"parent": ["Сначала переместите дочерние категории."]})
    return data


@app.get("/api/categories/")
def categories(actor=Depends(user)):
    with DB.connect() as db:
        return author_records(db, "categories", actor)


@app.post("/api/categories/", status_code=201)
def create_category(body: Category, actor=Depends(user)):
    staff(actor)
    with DB.connect(write=True) as db:
        data = category_values(db, None, body.model_dump(), actor)
        return db.insert("categories", {**data, "owner": actor["id"], "created_at": now()})


@app.get("/api/categories/{category_id}/")
def category_detail(category_id: int, actor=Depends(user)):
    with DB.connect() as db:
        category = db.get("categories", category_id)
        owned(category, actor)
        return category


@app.patch("/api/categories/{category_id}/")
@app.put("/api/categories/{category_id}/")
def edit_category(category_id: int, body: Category, actor=Depends(user)):
    with DB.connect(write=True) as db:
        category = db.get("categories", category_id, lock=True)
        owned(category, actor)
        values = {key: category[key] for key in Category.model_fields}
        values.update(body.model_dump(exclude_unset=True))
        return db.update("categories", category_id, category_values(db, category_id, values, actor))


@app.delete("/api/categories/{category_id}/", status_code=204)
def delete_category(category_id: int, actor=Depends(user)):
    with DB.connect(write=True) as db:
        owned(db.get("categories", category_id, lock=True), actor)
        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def question_view(db, question):
    category = db.get("categories", question["category_id"]) if question["category_id"] else None
    data = {key: value for key, value in question.items() if key != "category_id"}
    return {**data, "category": category, "base_points": format_points(question["base_points"]),
            "payload": json.loads(question["payload"]), "is_bank_question": bool(question["is_bank_question"])}


def question_values(db, data, actor):
    title_required(data)
    if not data["prompt"].strip():
        error(400, {"prompt": ["Введите условие."]})
    if data["category_id"] is not None:
        owned(db.get("categories", data["category_id"]), actor)
    payload = data["payload"]
    kind = data["question_type"]
    if kind in {"single", "multiple"}:
        options = payload.get("options")
        if (not isinstance(options, list) or len(options) < 2
                or any(not isinstance(item, dict) or not isinstance(item.get("id"), (str, int)) for item in options)):
            error(400, {"payload": ["Нужно минимум два корректных варианта."]})
        ids = {item["id"] for item in options}
        correct = [payload.get("correct_option")] if kind == "single" else payload.get("correct_options")
        if not isinstance(correct, list) or not correct or any(not isinstance(key, (int, str)) or key not in ids for key in correct):
            error(400, {"payload": ["Укажите корректный ответ."]})
    if kind == "text":
        answers = payload.get("correct_answers")
        if not isinstance(answers, list) or not answers or any(not isinstance(item, str) or not item.strip() for item in answers):
            error(400, {"payload": ["Укажите допустимые ответы."]})
    return {**data, "payload": document(payload), "base_points": format_points(data["base_points"]),
            "is_bank_question": int(data["is_bank_question"]), "updated_at": now()}


@app.get("/api/questions/")
def questions(question_type: str | None = None, category: int | None = None, is_bank_question: bool | None = None,
              search: str = "", ordering: str = "-updated_at", actor=Depends(user)):
    with DB.connect() as db:
        records = author_records(db, "questions", actor)
        chosen = [question_view(db, item) for item in records if (question_type is None or item["question_type"] == question_type)
                  and (category is None or item["category_id"] == category)
                  and (is_bank_question is None or bool(item["is_bank_question"]) == is_bank_question)
                  and search.casefold() in (item["title"] + " " + item["prompt"]).casefold()]
    key = ordering.lstrip("-")
    if key in {"base_points", "created_at", "updated_at"}:
        chosen.sort(key=lambda item: Decimal(item[key]) if key == "base_points" else item[key], reverse=ordering.startswith("-"))
    return chosen


def insert_question(db, body, actor):
    data = question_values(db, body.model_dump(), actor)
    return db.insert("questions", {**data, "owner": actor["id"], "created_at": now()})


@app.post("/api/questions/", status_code=201)
def create_question(body: Question, actor=Depends(user)):
    staff(actor)
    with DB.connect(write=True) as db:
        return question_view(db, insert_question(db, body, actor))


@app.post("/api/questions/generate/", response_model=Draft)
async def generate_question(body: GenerationInput, actor=Depends(user)):
    staff(actor)
    return await generate_draft(body)


@app.get("/api/questions/{question_id}/")
def question_detail(question_id: int, actor=Depends(user)):
    with DB.connect() as db:
        item = db.get("questions", question_id)
        owned(item, actor)
        return question_view(db, item)


@app.patch("/api/questions/{question_id}/")
@app.put("/api/questions/{question_id}/")
def edit_question(question_id: int, body: Question, actor=Depends(user)):
    with DB.connect(write=True) as db:
        item = db.get("questions", question_id, lock=True)
        owned(item, actor)
        data = {key: item[key] for key in Question.model_fields}
        data["payload"] = json.loads(item["payload"])
        data.update(body.model_dump(exclude_unset=True))
        return question_view(db, db.update("questions", question_id, question_values(db, data, actor)))


@app.delete("/api/questions/{question_id}/", status_code=204)
def delete_question(question_id: int, actor=Depends(user)):
    with DB.connect(write=True) as db:
        owned(db.get("questions", question_id, lock=True), actor)
        if db.one("SELECT tq.id FROM test_questions tq JOIN tests t ON t.id = tq.test "
                  "WHERE tq.question = ? AND t.is_frozen = 1", (question_id,)):
            error(400, "Вопрос используется в начатом тесте.")
        affected = db.all("SELECT DISTINCT test FROM test_questions WHERE question = ?", (question_id,))
        db.execute("DELETE FROM test_questions WHERE question = ?", (question_id,))
        db.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        for item in affected:
            normalize_order(db, item["test"])


def test_items(db, test_id, *, safe=False):
    rows = db.all("SELECT * FROM test_questions WHERE test = ? ORDER BY position, id", (test_id,))
    return [item_view(db, row, safe=safe) for row in rows]


def item_view(db, item, *, safe=False):
    question = question_view(db, db.get("questions", item["question"]))
    if safe:
        question["payload"] = student_payload(question["payload"])
    return {**{key: value for key, value in item.items() if key != "position"}, "order": item["position"],
            "question_data": question}


def max_points(item):
    return Decimal(item["overridden_points"] if item["overridden_points"] is not None else item["question_data"]["base_points"])


def test_view(db, record, *, safe=False, used=None):
    items = test_items(db, record["id"], safe=safe)
    availability = None
    if used is not None:
        code, label = "available", "Пройти"
        if record["deadline"] and parse_time(record["deadline"]) < parse_time(now()):
            code, label = "deadline_passed", "Дедлайн просрочен"
        elif record["attempts_limit"] is not None and used >= record["attempts_limit"]:
            code, label = "attempts_exhausted", "Попытки исчерпаны"
        availability = {"code": code, "label": label, "can_start": code == "available",
                        "attempts_used": used, "attempts_limit": record["attempts_limit"]}
    return {**{key: value for key, value in record.items() if key != "archived"},
            "is_frozen": bool(record["is_frozen"]), "test_questions": items,
            "questions_count": len(items), "max_score": format_points(sum(map(max_points, items))),
            "availability": availability}


def with_authors(records):
    if not records:
        return records
    try:
        people = call("identity", "/internal/users-batch", method="POST",
                      body=sorted({item["owner"] for item in records}))
    except HTTPException:
        people = []  # Viewing tests remains available during an identity outage.
    names = {person["id"]: " ".join(filter(None, [person.get("last_name"), person.get("first_name")])).strip()
             for person in people}
    return [{**item, "author_name": names.get(item["owner"]) or None} for item in records]


def student_group_ids(actor):
    return set(call("groups", f"/internal/students/{actor['id']}/groups/", retries=1, breaker=group_breaker))


def assignment_visible(item, student, groups):
    return item["student"] == student or item["group_id"] in groups


def student_tests(actor):
    group_ids = student_group_ids(actor)
    used = call("attempts", f"/internal/students/{actor['id']}/counts/", breaker=attempts_breaker)
    with DB.connect() as db:
        permitted = {item["test"] for item in db.all("SELECT * FROM assignments")
                     if assignment_visible(item, actor["id"], group_ids)}
        return with_authors([test_view(db, item, safe=True, used=used.get(str(item["id"]), 0))
                for item in db.all("SELECT * FROM tests WHERE archived = 0 ORDER BY updated_at DESC, id DESC") if item["id"] in permitted])


@app.get("/api/tests/available/")
def available(actor=Depends(user)):
    return student_tests(actor) if actor["role"] == "student" else []


@app.get("/api/tests/")
def tests(search: str = "", actor=Depends(user)):
    if actor["role"] == "student":
        result = student_tests(actor)
    else:
        with DB.connect() as db:
            result = [test_view(db, item) for item in author_records(db, "tests", actor, condition="archived = 0")]
        result.sort(key=lambda item: item["updated_at"], reverse=True)
        result = with_authors(result)
    return [item for item in result if search.casefold() in (item["title"] + " " + item["description"]).casefold()]


def test_values(body, *, patch=False):
    values = body.model_dump(exclude_unset=patch)
    deadline = values.get("deadline")
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=ZoneInfo("Europe/Moscow"))
        values["deadline"] = deadline.isoformat()
    return {**values, "updated_at": now()}


@app.post("/api/tests/", status_code=201)
def create_test(body: TestInput, actor=Depends(user)):
    staff(actor)
    values = test_values(body)
    title_required(values)
    with DB.connect(write=True) as db:
        record = db.insert("tests", {**values, "owner": actor["id"], "created_at": now()})
        return test_view(db, record)


@app.post("/api/tests/generate/", response_model=GeneratedTest)
async def generate_test_draft(body: TestGenerationInput, actor=Depends(user)):
    staff(actor)
    return await generate_test(body)


def bank_draft_values(db, question, actor):
    values = question_values(db, {**question.model_dump(include=set(Question.model_fields)), "is_bank_question": True}, actor)
    if question.question_type in {"single", "multiple"}:
        options = question.payload["options"]
        if (len({item["id"] for item in options}) != len(options)
                or any(not isinstance(item.get("text"), str) or not item["text"].strip() for item in options)):
            error(400, {"payload": ["Заполните все варианты и укажите разные идентификаторы."]})
    return values


def draft_fingerprint(body):
    data = body.model_dump(mode="json")
    # Preserve fingerprints of requests saved before optional identity/version fields existed.
    for key in ("test_id", "expected_updated_at"):
        if data[key] is None:
            data.pop(key)
    for question in data["questions"]:
        for key in ("id", "expected_updated_at", "overridden_points"):
            if question[key] is None:
                question.pop(key)
    return sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@app.post("/api/tests/save-draft/", status_code=201)
def save_test_draft(body: DraftTestInput, idempotency_key: Annotated[UUID, Header()], actor=Depends(user)):
    staff(actor)
    values = test_values(body.test)
    title_required(values)
    fingerprint = draft_fingerprint(body)
    owner, request_key = actor["id"], str(idempotency_key)
    with DB.connect(write=True) as db:
        reservation = db.one(
            "INSERT INTO test_save_requests (owner, request_key, fingerprint, result) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (owner, request_key) DO NOTHING RETURNING request_key",
            (owner, request_key, fingerprint, ""),
        )
        if not reservation:
            previous = db.one("SELECT fingerprint, result FROM test_save_requests WHERE owner = ? AND request_key = ?",
                              (owner, request_key))
            if previous["fingerprint"] != fingerprint:
                error(409, "Этот черновик уже сохранён с другими данными. Проверьте список «Мои тесты».")
            return json.loads(previous["result"])

        # Lock existing records in a stable order before checking optimistic versions.
        record = edit_test(db, body.test_id, actor) if body.test_id else None
        if record and record["updated_at"] != body.expected_updated_at:
            error(409, "Тест уже изменён. Откройте его заново перед сохранением.")
        ids = [item.id for item in body.questions if item.id is not None]
        if len(ids) != len(set(ids)):
            error(400, "Вопрос банка нельзя добавить в тест дважды.")
        existing = {}
        for question_id in sorted(ids):
            row = db.get("questions", question_id, lock=True)
            owned(row, actor)
            existing[question_id] = row
        prepared = []
        for item in body.questions:
            row = existing.get(item.id)
            if row and row["updated_at"] != item.expected_updated_at:
                error(409, "Вопрос «" + row["title"] + "» уже изменён в банке. Откройте тест заново.")
            question_values_to_save = bank_draft_values(db, item, actor)
            if row:
                question_values_to_save["is_bank_question"] = row["is_bank_question"]
            prepared.append(question_values_to_save)
        timestamp = now()
        record = (db.update("tests", body.test_id, values) if record else
                  db.insert("tests", {**values, "owner": owner, "created_at": timestamp}))
        db.execute("DELETE FROM test_questions WHERE test = ?", (record["id"],))
        added = 0
        for position, (item, values) in enumerate(zip(body.questions, prepared), start=1):
            if item.id is None:
                question = db.insert("questions", {**values, "owner": owner, "created_at": timestamp})
                added += 1
            else:
                row = existing[item.id]
                changed = any(row[key] != value for key, value in values.items() if key != "updated_at")
                question = db.update("questions", item.id, values) if changed else row
            db.insert("test_questions", {"test": record["id"], "question": question["id"], "position": position,
                      "overridden_points": (format_points(item.overridden_points)
                                            if item.overridden_points is not None else None), "created_at": timestamp})
        result = {"test": test_view(db, record), "questions_added": added}
        db.execute("UPDATE test_save_requests SET result = ? WHERE owner = ? AND request_key = ?",
                   (document(result), owner, request_key))
        return result


@app.get("/api/tests/{test_id}/")
def test_detail(test_id: int, actor=Depends(user)):
    if actor["role"] == "student":
        for item in student_tests(actor):
            if item["id"] == test_id:
                return item
        error(404, "Тест недоступен.")
    with DB.connect() as db:
        record = db.get("tests", test_id)
        owned(record, actor)
        if record["archived"]:
            error(404, "Тест не найден.")
        return with_authors([test_view(db, record)])[0]


def edit_test(db, test_id, actor, *, frozen_allowed=False):
    staff(actor)
    record = db.get("tests", test_id, lock=True)
    owned(record, actor)
    if record["archived"]:
        error(404, "Тест не найден.")
    if record["is_frozen"] and not frozen_allowed:
        error(400, "Прохождение теста уже началось. Состав и параметры этого теста больше нельзя редактировать.")
    return record


@app.patch("/api/tests/{test_id}/")
@app.put("/api/tests/{test_id}/")
def update_test(test_id: int, body: TestInput, actor=Depends(user)):
    with DB.connect(write=True) as db:
        record = edit_test(db, test_id, actor)
        values = test_values(body, patch=True)
        title_required({**record, **values})
        return test_view(db, db.update("tests", test_id, values))


@app.delete("/api/tests/{test_id}/", status_code=204)
def delete_test(test_id: int, actor=Depends(user)):
    with DB.connect(write=True) as db:
        record = edit_test(db, test_id, actor, frozen_allowed=True)
        if record["is_frozen"]:
            db.execute("DELETE FROM assignments WHERE test = ?", (test_id,))
            db.update("tests", test_id, {"archived": 1, "updated_at": now()})
        else:
            db.execute("DELETE FROM tests WHERE id = ?", (test_id,))


def normalize_order(db, test_id):
    for index, item in enumerate(db.all("SELECT id FROM test_questions WHERE test = ? ORDER BY position, id", (test_id,)), 1):
        db.update("test_questions", item["id"], {"position": index})


def insert_item(db, test_id, question, *, order=None, points=None):
    items = db.all("SELECT id, question FROM test_questions WHERE test = ? ORDER BY position, id", (test_id,))
    existing = next((item for item in items if item["question"] == question), None)
    values = {"overridden_points": None if points is None else format_points(points)}
    if existing:
        key = existing["id"]
        db.update("test_questions", key, values)
    else:
        key = db.insert("test_questions", {**values, "test": test_id, "question": question,
                                         "position": len(items) + 1, "created_at": now()})["id"]
    ordering = [item["id"] for item in items if item["id"] != key]
    ordering.insert(len(ordering) if order is None else order - 1, key)
    for index, item_id in enumerate(ordering, 1):
        db.update("test_questions", item_id, {"position": index})
    return item_view(db, db.get("test_questions", key))


@app.post("/api/tests/{test_id}/add-question/")
def add_question(test_id: int, body: ItemInput, actor=Depends(user)):
    with DB.connect(write=True) as db:
        edit_test(db, test_id, actor)
        question = db.get("questions", body.question, lock=True)
        owned(question, actor)
        return insert_item(db, test_id, body.question, order=body.order, points=body.overridden_points)


@app.post("/api/tests/{test_id}/create-inline-question/", status_code=201)
def inline_question(test_id: int, body: Question, actor=Depends(user)):
    with DB.connect(write=True) as db:
        edit_test(db, test_id, actor)
        question = insert_question(db, body.model_copy(update={"is_bank_question": False, "category_id": None}), actor)
        return insert_item(db, test_id, question["id"])


@app.post("/api/tests/{test_id}/remove-question/", status_code=204)
def remove_question(test_id: int, body: RemoveInput, actor=Depends(user)):
    with DB.connect(write=True) as db:
        edit_test(db, test_id, actor)
        key = body.test_question or body.question
        entry = db.one("SELECT id FROM test_questions WHERE test = ? AND id = ?", (test_id, key))
        if not entry and body.test_question is None:
            entry = db.one("SELECT id FROM test_questions WHERE test = ? AND question = ?", (test_id, key))
        if not entry:
            error(400, "Вопрос не найден в тесте.")
        db.execute("DELETE FROM test_questions WHERE id = ?", (entry["id"],))
        normalize_order(db, test_id)


@app.post("/api/tests/{test_id}/reorder-questions/")
def reorder(test_id: int, body: OrderInput, actor=Depends(user)):
    with DB.connect(write=True) as db:
        edit_test(db, test_id, actor)
        current = {item["id"] for item in test_items(db, test_id)}
        if len(body.order) != len(current) or set(body.order) != current:
            error(400, "Передайте все элементы теста без повторов.")
        for index, key in enumerate(body.order, 1):
            db.update("test_questions", key, {"position": index})
        return test_items(db, test_id)


@app.post("/api/tests/{test_id}/clone/", status_code=201)
def clone(test_id: int, actor=Depends(user)):
    with DB.connect(write=True) as db:
        source = edit_test(db, test_id, actor, frozen_allowed=True)
        fields = {field: source[field] for field in TestInput.model_fields}
        fields["title"] = (fields["title"][:247] + " (копия)")
        new = db.insert("tests", {**fields, "owner": actor["id"], "created_at": now(), "updated_at": now()})
        for item in test_items(db, test_id):
            insert_item(db, new["id"], item["question"], points=item["overridden_points"])
        return test_view(db, new)


def check_targets(actor, groups, students):
    if not groups and not students:
        error(400, "Укажите хотя бы одну группу или студента.")
    if groups:
        allowed = call("groups", f"/internal/teachers/{actor['id']}/groups/?admin={actor['role'] == 'admin'}",
                       retries=1, breaker=group_breaker)
        if not set(groups) <= {item["id"] for item in allowed}:
            error(403, "Можно назначать только своим группам.")
    if students:
        people = call("identity", "/internal/users-batch", method="POST", body=students)
        if set(students) != {item["id"] for item in people if item["role"] == "student" and item["is_active"] and not item["is_blocked"]}:
            error(400, "Укажите активных учащихся.")
        if actor["role"] != "admin":
            allowed = call("groups", f"/internal/teachers/{actor['id']}/students/", retries=1, breaker=group_breaker)
            if not set(students) <= set(allowed):
                error(403, "Можно назначать только учащимся из ваших групп.")


def store_assignment(db, test, actor, *, group=None, student=None):
    if group is not None:
        existing = db.one("SELECT * FROM assignments WHERE test = ? AND group_id = ?", (test, group))
    else:
        existing = db.one("SELECT * FROM assignments WHERE test = ? AND student = ?", (test, student))
    if existing:
        return existing
    return db.insert("assignments", {"test": test, "group_id": group, "student": student,
                                    "assigned_by": actor["id"], "created_at": now()})


def assignment_view(item):
    return {**{key: value for key, value in item.items() if key != "group_id"}, "group": item["group_id"]}


@app.post("/api/tests/{test_id}/assign/")
def assign(test_id: int, body: AssignmentInput, actor=Depends(user)):
    staff(actor)
    with DB.connect() as db:
        owned(db.get("tests", test_id), actor)
    check_targets(actor, body.group_ids, body.student_ids)
    with DB.connect(write=True) as db:
        edit_test(db, test_id, actor, frozen_allowed=True)
        db.execute("DELETE FROM assignments WHERE test = ?", (test_id,))
        for key in dict.fromkeys(body.group_ids):
            store_assignment(db, test_id, actor, group=key)
        for key in dict.fromkeys(body.student_ids):
            store_assignment(db, test_id, actor, student=key)
    return {"detail": "Тест назначен."}


@app.get("/api/assignments/targets/")
def targets(actor=Depends(user)):
    if actor["role"] == "student":
        return {"groups": [], "students": []}
    all_groups = call("groups", f"/internal/teachers/{actor['id']}/groups/?admin={actor['role'] == 'admin'}")
    if actor["role"] == "admin":
        people = call("identity", "/internal/students/")
    else:
        keys = call("groups", f"/internal/teachers/{actor['id']}/students/")
        people = call("identity", "/internal/users-batch", method="POST", body=keys)
    return {"groups": all_groups, "students": people}


@app.get("/api/assignments/")
def list_assignments(test: int | None = None, actor=Depends(user)):
    groups = student_group_ids(actor) if actor["role"] == "student" else set()
    with DB.connect() as db:
        rows = db.all("SELECT a.*, t.owner FROM assignments a JOIN tests t ON a.test = t.id ORDER BY a.id DESC")
    result = []
    for item in rows:
        if test is not None and item["test"] != test:
            continue
        if (actor["role"] == "admin" or (actor["role"] == "teacher" and item["owner"] == actor["id"])
                or (actor["role"] == "student" and assignment_visible(item, actor["id"], groups))):
            result.append(assignment_view({key: value for key, value in item.items() if key != "owner"}))
    return result


@app.post("/api/assignments/", status_code=201)
def create_assignment(body: SingleAssignment, actor=Depends(user)):
    staff(actor)
    if (body.group is None) == (body.student is None):
        error(400, "Выберите группу или учащегося.")
    check_targets(actor, [body.group] if body.group else [], [body.student] if body.student else [])
    with DB.connect(write=True) as db:
        edit_test(db, body.test, actor, frozen_allowed=True)
        return assignment_view(store_assignment(db, body.test, actor, group=body.group, student=body.student))


@app.get("/api/assignments/{assignment_id}/")
def assignment_detail(assignment_id: int, actor=Depends(user)):
    for assignment in list_assignments(actor=actor):
        if assignment["id"] == assignment_id:
            return assignment
    error(404, "Назначение не найдено.")


@app.delete("/api/assignments/{assignment_id}/", status_code=204)
def delete_assignment(assignment_id: int, actor=Depends(user)):
    staff(actor)
    with DB.connect(write=True) as db:
        assignment = db.get("assignments", assignment_id)
        edit_test(db, assignment["test"], actor, frozen_allowed=True)
        db.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))


@app.post("/internal/tests/{test_id}/start/", dependencies=[Depends(internal)])
def prepare_attempt(test_id: int, body: Start):
    groups = student_group_ids({"id": body.student})
    with DB.connect(write=True) as db:
        record = db.get("tests", test_id, lock=True)
        if record["archived"] or not any(assignment_visible(item, body.student, groups)
                   for item in db.all("SELECT * FROM assignments WHERE test = ?", (test_id,))):
            error(403, "Этот тест вам не назначен.")
        if record["deadline"] and parse_time(record["deadline"]) < parse_time(now()):
            error(400, "Дедлайн истёк, начать тест нельзя.")
        if not record["is_frozen"]:
            record = db.update("tests", test_id, {"is_frozen": 1})
        return test_view(db, record)


@app.get("/api/tests/{test_id}/stats/")
def stats(test_id: int, actor=Depends(user)):
    staff(actor)
    with DB.connect() as db:
        record = db.get("tests", test_id)
        owned(record, actor)
        assigned = db.all("SELECT group_id, student FROM assignments WHERE test = ?", (test_id,))
        items = test_items(db, test_id)
    group_ids = sorted({item["group_id"] for item in assigned if item["group_id"] is not None})
    students = {item["student"] for item in assigned if item["student"] is not None}
    if group_ids:
        students.update(call("groups", "/internal/groups/students/", method="POST", body=group_ids))
    data = call("attempts", f"/internal/tests/{test_id}/stats/", breaker=attempts_breaker, retries=1)
    questions = data.pop("question_stats")
    max_score = float(sum(map(max_points, items)))
    computed = []
    for item in items:
        aggregates = questions.get(str(item["id"]))
        max_item = float(max_points(item))
        count = aggregates["count"] if aggregates else 0
        average = float(aggregates["points"]) / count if count else 0
        computed.append({"test_question_id": item["id"], "question_id": item["question"],
                         "title": item["question_data"]["title"],
                         "correct_pct": aggregates["correct"] / count * 100 if count else 0,
                         "avg_points": average, "avg_points_pct": average / max_item * 100 if max_item else 0})
    average_score = data.pop("avg_score")
    return {**data, "assigned_students": len(students), "question_stats": computed,
            "avg_score_pct": round(average_score / max_score * 100, 2) if max_score else 0}


def record_attempt_event(event_id, kind, payload):
    event = {**payload, "kind": kind}
    with DB.connect(write=True) as db:
        inserted = db.one("INSERT INTO attempt_updates (event_id, attempt, test_id, revision, data) VALUES (?, ?, ?, ?, ?) "
                          "ON CONFLICT DO NOTHING RETURNING id",
                          (event_id, event["attempt"], event["test"], event["revision"], document(event)))
    return inserted is not None


def authorize_stream(test_id: int, actor=Depends(user)):
    staff(actor)
    with DB.connect() as db:
        owned(db.get("tests", test_id), actor)


def stream_events(test_id, cursor):
    with DB.connect() as db:
        records = db.all("SELECT id, data FROM attempt_updates WHERE test_id = ? AND id > ? ORDER BY id LIMIT 100",
                         (test_id, cursor))
    return [(item["id"], json.loads(item["data"])) for item in records]


@app.get("/api/tests/{test_id}/events/", response_class=EventSourceResponse,
         dependencies=[Depends(authorize_stream)])
async def test_events(test_id: int, request: Request, last_event_id: Annotated[int, Header(ge=0)] = 0):
    cursor = last_event_id
    while not await request.is_disconnected():
        for cursor, event in await run_in_threadpool(stream_events, test_id, cursor):
            yield ServerSentEvent(id=str(cursor), event=event["kind"], data=event)
        await asyncio.sleep(0.4)
