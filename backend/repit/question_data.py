from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

QuestionType = Literal["single", "multiple", "text", "extended"]
QuestionTitle = Annotated[str, Field(max_length=255)]
QuestionPrompt = Annotated[str, Field(max_length=30000)]


def format_points(points):
    return f"{Decimal(points):.2f}"


def student_payload(payload):
    return {"options": [{key: opt[key] for key in ("id", "text", "label") if key in opt}
                        for opt in payload.get("options", []) if isinstance(opt, dict)]} if "options" in payload else {}


