import json
from datetime import datetime, timezone

def now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def document(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
