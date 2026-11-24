import contextvars
import json
import logging
import os

SERVICE = os.getenv("SERVICE", "local")
REQUEST_ID = contextvars.ContextVar("request_id", default="-")
logging.basicConfig(level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger("repit")

def log(event, **fields):
    LOGGER.info(json.dumps({"service": SERVICE, "request_id": REQUEST_ID.get(), "event": event, **fields}))
