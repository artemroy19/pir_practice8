import json
from datetime import timedelta
from decimal import Decimal

from fastapi import Depends, Response
from pydantic import BaseModel, Field

from ..auth import internal, user
from ..database import Database
from ..http_app import app_for, error
from ..observability import REQUEST_ID
from ..question_data import format_points, student_payload
from ..scoring import score_question
from ..service_client import CircuitBreaker, call
from ..values import document, now, parse_time

DB = Database("attempts")
SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
 id AUTO_ID, test BIGINT NOT NULL, owner BIGINT NOT NULL, student BIGINT NOT NULL,
 attempt_number INTEGER NOT NULL, test_title TEXT NOT NULL, timer_minutes INTEGER, deadline TEXT,
 result_visibility TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
 auto_score TEXT NOT NULL DEFAULT '0.00', manual_score TEXT NOT NULL DEFAULT '0.00',
 total_score TEXT NOT NULL DEFAULT '0.00', essay_review_pending INTEGER NOT NULL DEFAULT 0,
 is_overdue INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0, UNIQUE(test, student, attempt_number)
);
CREATE TABLE IF NOT EXISTS answers (
 id AUTO_ID, attempt BIGINT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
 test_question BIGINT NOT NULL, question_id BIGINT NOT NULL, question_title TEXT NOT NULL,
 question_type TEXT NOT NULL, question_prompt TEXT NOT NULL, question_payload TEXT NOT NULL,
 position INTEGER NOT NULL, max_points TEXT NOT NULL, answer_payload TEXT NOT NULL DEFAULT '{}',
 is_correct INTEGER, auto_points TEXT NOT NULL DEFAULT '0.00', manual_points TEXT NOT NULL DEFAULT '0.00',
 teacher_comment TEXT NOT NULL DEFAULT '', reviewed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(attempt, test_question)
);
CREATE TABLE IF NOT EXISTS outbox (
 id AUTO_ID, kind TEXT NOT NULL, payload TEXT NOT NULL, correlation_id TEXT NOT NULL,
 sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(sent, id);
CREATE INDEX IF NOT EXISTS attempts_student ON attempts(student);
CREATE INDEX IF NOT EXISTS attempts_owner ON attempts(owner);
"""
app = app_for("РепИТ · Попытки и оценивание", DB, SCHEMA)
catalog_breaker = CircuitBreaker()


class Start(BaseModel):
    test: int


class Answer(BaseModel):
    test_question: int
    answer_payload: dict = Field(default_factory=dict)


class Review(BaseModel):
    answer_id: int
    manual_points: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    teacher_comment: str = Field(default="", max_length=10000)


def attempt_scope(actor):
    if actor["role"] == "teacher":
        return "owner = ?", [actor["id"]]
    if actor["role"] == "student":
        return "student = ?", [actor["id"]]
    return "1 = 1", []


def visible(db, key, actor, *, lock=False):
    condition, values = attempt_scope(actor)
    attempt = db.one("SELECT * FROM attempts WHERE id = ? AND " + condition, (key, *values), lock=lock)
    if attempt is None:
        error(404, "Попытка не найдена.")
    return attempt


def load_answers(db, key):
    return db.all("SELECT * FROM answers WHERE attempt = ? ORDER BY position, id", (key,))


def attempt_view(db, attempt, actor, names):
    answers = load_answers(db, attempt["id"])
    may_review = actor["role"] != "student" or (
        attempt["status"] == "completed" and attempt["result_visibility"] == "score_with_review")
    rendered = []
    for answer in answers:
        data = {key: value for key, value in answer.items() if key != "position"}
        payload = json.loads(answer["question_payload"])
        data["question_payload"] = payload if may_review else student_payload(payload)
        data["answer_payload"] = json.loads(answer["answer_payload"])
        data["is_correct"] = bool(answer["is_correct"]) if may_review and answer["is_correct"] is not None else None
        data["order"] = answer["position"]
        data["earned_points"] = format_points(Decimal(answer["auto_points"]) + Decimal(answer["manual_points"]))
        rendered.append(data)
    result = {key: value for key, value in attempt.items() if key not in {"owner", "revision", "deadline"}}
    result.update(student_name=names.get(attempt["student"], ""), answers=rendered,
                  max_score=format_points(sum(Decimal(answer["max_points"]) for answer in answers)),
                  is_overdue=bool(attempt["is_overdue"]), essay_review_pending=bool(attempt["essay_review_pending"]))
    return result


def names_for(records):
    if not records:
        return {}
    accounts = call("identity", "/internal/users-batch", method="POST",
                    body=sorted({item["student"] for item in records}))
    return {item["id"]: " ".join(filter(None, (item["last_name"], item["first_name"]))) or item["email"]
            for item in accounts}


def single_view(key, actor):
    with DB.connect() as db:
        attempt = visible(db, key, actor)
    names = names_for([attempt])
    with DB.connect() as db:
        return attempt_view(db, visible(db, key, actor), actor, names)


def queue_event(db, attempt, kind):
    data = {"attempt": attempt["id"], "test": attempt["test"], "student": attempt["student"],
            "revision": attempt["revision"], "status": attempt["status"], "total_score": attempt["total_score"],
            "essay_review_pending": bool(attempt["essay_review_pending"])}
    db.insert("outbox", {"kind": kind, "payload": document(data), "correlation_id": REQUEST_ID.get()})


@app.get("/api/attempts/")
def list_attempts(test: int | None = None, student: int | None = None, attempt_number: int | None = None,
                  is_overdue: bool | None = None, essay_review_pending: bool | None = None, actor=Depends(user)):
    scope, values = attempt_scope(actor)
    filters = [scope]
    for field, value in (("test", test), ("student", student), ("attempt_number", attempt_number),
                         ("is_overdue", None if is_overdue is None else int(is_overdue)),
                         ("essay_review_pending", None if essay_review_pending is None else int(essay_review_pending))):
        if value is not None:
            filters.append(f"{field} = ?")
            values.append(value)
    with DB.connect() as db:
        records = db.all("SELECT * FROM attempts WHERE " + " AND ".join(filters) + " ORDER BY id DESC", values)
    names = names_for(records)
    with DB.connect() as db:
        return [attempt_view(db, attempt, actor, names) for attempt in records]


@app.get("/api/attempts/{attempt_id}/")
def detail(attempt_id: int, actor=Depends(user)):
    return single_view(attempt_id, actor)


@app.post("/api/attempts/start/")
def start(body: Start, response: Response, actor=Depends(user)):
    if actor["role"] != "student":
        error(403, "Начать попытку может только учащийся.")
    with DB.connect(write=True) as db:
        db.serialize_start(body.test, actor["id"])
        prior = db.all("SELECT * FROM attempts WHERE test = ? AND student = ? ORDER BY attempt_number DESC",
                       (body.test, actor["id"]))
        if prior and prior[0]["status"] == "in_progress":
            key = prior[0]["id"]
        else:
            test = call("catalog", f"/internal/tests/{body.test}/start/", method="POST", breaker=catalog_breaker,
                        body={"student": actor["id"]})
            if test["attempts_limit"] is not None and len(prior) >= test["attempts_limit"]:
                error(400, "Доступные попытки исчерпаны.")
            timestamp = now()
            attempt = db.insert("attempts", {
                "test": body.test, "owner": test["owner"], "student": actor["id"], "attempt_number": len(prior) + 1,
                "test_title": test["title"], "timer_minutes": test["timer_minutes"], "deadline": test["deadline"],
                "result_visibility": test["result_visibility"], "status": "in_progress",
                "started_at": timestamp, "created_at": timestamp, "updated_at": timestamp,
            })
            key = attempt["id"]
            for item in test["test_questions"]:
                question = item["question_data"]
                points = item["overridden_points"] if item["overridden_points"] is not None else question["base_points"]
                db.insert("answers", {
                    "attempt": key, "test_question": item["id"], "question_id": question["id"],
                    "question_title": question["title"], "question_type": question["question_type"],
                    "question_prompt": question["prompt"], "question_payload": document(question["payload"]),
                    "position": item["order"], "max_points": format_points(points),
                    "created_at": timestamp, "updated_at": timestamp,
                })
            response.status_code = 201
    return single_view(key, actor)


def is_late(attempt, timestamp, *, grace_seconds=0):
    limits = []
    if attempt["deadline"]:
        limits.append(parse_time(attempt["deadline"]))
    if attempt["timer_minutes"]:
        limits.append(parse_time(attempt["started_at"]) + timedelta(minutes=attempt["timer_minutes"]))
    return bool(limits and parse_time(timestamp) > min(limits) + timedelta(seconds=grace_seconds))


def validate_answer(kind, payload):
    selected = payload.get("selected")
    if kind == "single" and selected is not None and not isinstance(selected, (int, str)):
        error(400, "Некорректный вариант.")
    if kind == "multiple" and "selected" in payload and (
            not isinstance(selected, list) or any(not isinstance(item, (str, int)) for item in selected)):
        error(400, "Передайте список вариантов.")
    if kind in {"text", "extended"} and "value" in payload and not isinstance(payload["value"], str):
        error(400, "Ответ должен быть текстом.")
    if len(document(payload).encode()) > 65536:
        error(400, "Ответ слишком длинный.")


@app.post("/api/attempts/{attempt_id}/save-answer/")
def save_answer(attempt_id: int, body: Answer, actor=Depends(user)):
    with DB.connect(write=True) as db:
        attempt = visible(db, attempt_id, actor, lock=True)
        if attempt["student"] != actor["id"]:
            error(403, "Эта попытка принадлежит другому учащемуся.")
        if attempt["status"] != "in_progress":
            error(400, "Попытка уже завершена.")
        timestamp = now()
        if is_late(attempt, timestamp, grace_seconds=3):
            error(400, "Время ответа истекло.")
        answer = db.one("SELECT * FROM answers WHERE attempt = ? AND test_question = ?", (attempt_id, body.test_question))
        if not answer:
            error(400, "Вопрос не принадлежит этой попытке.")
        validate_answer(answer["question_type"], body.answer_payload)
        db.update("answers", answer["id"], {"answer_payload": document(body.answer_payload), "updated_at": timestamp})
    return {"detail": "Ответ сохранён."}


@app.post("/api/attempts/{attempt_id}/submit/")
def submit(attempt_id: int, actor=Depends(user)):
    with DB.connect(write=True) as db:
        attempt = visible(db, attempt_id, actor, lock=True)
        if actor["role"] != "admin" and (actor["role"] != "student" or attempt["student"] != actor["id"]):
            error(403, "Вы не можете завершить эту попытку.")
        if attempt["status"] == "in_progress":
            timestamp = now()
            auto_score = Decimal(0)
            pending = False
            for answer in load_answers(db, attempt_id):
                kind = answer["question_type"]
                pending = pending or kind == "extended"
                correct, score = score_question(kind, json.loads(answer["answer_payload"]),
                                                json.loads(answer["question_payload"]), answer["max_points"])
                auto_score += score
                db.update("answers", answer["id"], {"is_correct": None if correct is None else int(correct),
                                                     "auto_points": format_points(score), "updated_at": timestamp})
            attempt = db.update("attempts", attempt_id, {
                "status": "completed", "ended_at": timestamp, "auto_score": format_points(auto_score),
                "total_score": format_points(auto_score), "is_overdue": int(is_late(attempt, timestamp, grace_seconds=3)),
                "essay_review_pending": int(pending), "updated_at": timestamp, "revision": 1,
            })
            queue_event(db, attempt, "AttemptSubmitted")
    return single_view(attempt_id, actor)


@app.post("/api/attempts/{attempt_id}/review-essay/")
def review(attempt_id: int, body: Review, actor=Depends(user)):
    if actor["role"] not in {"teacher", "admin"}:
        error(403, "Проверять развёрнутые ответы может преподаватель.")
    with DB.connect(write=True) as db:
        attempt = visible(db, attempt_id, actor, lock=True)
        if attempt["status"] != "completed":
            error(400, "Попытка ещё не завершена.")
        answer = db.one("SELECT * FROM answers WHERE attempt = ? AND id = ?", (attempt_id, body.answer_id))
        if not answer or answer["question_type"] != "extended":
            error(400, {"answer_id": ["Развёрнутый ответ не найден."]})
        if body.manual_points > Decimal(answer["max_points"]):
            error(400, {"manual_points": ["Балл выше максимума."]})
        if (answer["reviewed_at"] is None or Decimal(answer["manual_points"]) != body.manual_points
                or answer["teacher_comment"] != body.teacher_comment):
            timestamp = now()
            db.update("answers", answer["id"], {"manual_points": format_points(body.manual_points),
                      "teacher_comment": body.teacher_comment, "reviewed_at": timestamp, "updated_at": timestamp})
            answers = load_answers(db, attempt_id)
            manual_score = sum(Decimal(item["manual_points"]) for item in answers)
            pending = any(item["question_type"] == "extended" and item["reviewed_at"] is None for item in answers)
            attempt = db.update("attempts", attempt_id, {
                "manual_score": format_points(manual_score),
                "total_score": format_points(Decimal(attempt["auto_score"]) + manual_score),
                "essay_review_pending": int(pending), "updated_at": timestamp, "revision": attempt["revision"] + 1,
            })
            queue_event(db, attempt, "AttemptReviewed")
    return single_view(attempt_id, actor)


@app.get("/api/essay-review-queue/")
def review_queue(actor=Depends(user)):
    return list_attempts(essay_review_pending=True, actor=actor) if actor["role"] != "student" else []


@app.get("/api/essay-review-summary/")
def review_summary(actor=Depends(user)):
    if actor["role"] == "student":
        error(403, "Сводка доступна преподавателю.")
    scope, values = attempt_scope(actor)
    with DB.connect() as db:
        return db.all("SELECT test AS test_id, test_title AS \"test__title\", COUNT(*) AS pending "
                      "FROM attempts WHERE essay_review_pending = 1 AND " + scope
                      + " GROUP BY test, test_title ORDER BY pending DESC", values)


@app.get("/internal/students/{student_id}/counts/", dependencies=[Depends(internal)])
def counts(student_id: int):
    with DB.connect() as db:
        return {str(row["test"]): row["n"] for row in db.all(
            "SELECT test, COUNT(*) AS n FROM attempts WHERE student = ? GROUP BY test", (student_id,))}


@app.get("/internal/tests/{test_id}/stats/", dependencies=[Depends(internal)])
def stats(test_id: int):
    with DB.connect() as db:
        attempts = db.all("SELECT id, student, total_score, started_at, ended_at, is_overdue "
                          "FROM attempts WHERE test = ? AND status = 'completed'", (test_id,))
        answers = db.all("SELECT a.test_question, a.is_correct, a.auto_points, a.manual_points FROM answers a "
                         "JOIN attempts t ON t.id = a.attempt WHERE t.test = ? AND t.status = 'completed'", (test_id,))
    size = len(attempts)
    questions = {}
    for item in answers:
        values = questions.setdefault(str(item["test_question"]), {"count": 0, "correct": 0, "points": Decimal(0)})
        values["count"] += 1
        values["correct"] += int(item["is_correct"] == 1)
        values["points"] += Decimal(item["auto_points"]) + Decimal(item["manual_points"])
    return {
        "completed_students": len({item["student"] for item in attempts}), "used_attempts": size,
        "avg_score": float(sum(Decimal(item["total_score"]) for item in attempts) / size) if size else 0,
        "avg_duration_seconds": int(sum((parse_time(item["ended_at"]) - parse_time(item["started_at"])).total_seconds()
                                        for item in attempts) / size) if size else None,
        "overdue_pct": round(100 * sum(item["is_overdue"] for item in attempts) / size, 2) if size else 0,
        "question_stats": questions,
    }
