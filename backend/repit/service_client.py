import os
import threading
import time

import httpx

from .auth import INTERNAL_KEY
from .http_app import error
from .observability import REQUEST_ID, log

HTTP = httpx.Client(timeout=httpx.Timeout(1.0, connect=0.5), trust_env=False)

class CircuitBreaker:
    def __init__(self, threshold=2, cooldown=5, clock=time.monotonic):
        self.threshold = threshold
        self.cooldown = cooldown
        self.clock = clock
        self.failures = 0
        self.until = 0
        self.probe = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.probe or self.until > self.clock():
                log("circuit.open")
                error(503, "Зависимый сервис временно недоступен.")
            self.probe = bool(self.until)

    def finish(self, ok):
        with self.lock:
            if ok:
                self.failures = self.until = 0
            else:
                self.failures += 1
                if self.probe or self.failures >= self.threshold:
                    self.until = self.clock() + self.cooldown
            self.probe = False


def call(service, path, *, method="GET", body=None, retries=0, breaker=None):
    url = os.getenv(f"{service.upper()}_URL", f"http://{service}-service:8000")
    if breaker:
        breaker.start()
    ok = False
    try:
        for attempt in range(retries + 1):
            try:
                response = HTTP.request(method, url + path, json=body, headers={
                    "X-Internal-Key": INTERNAL_KEY, "X-Request-ID": REQUEST_ID.get(),
                })
                if response.status_code < 500:
                    ok = True
                    if response.status_code >= 400:
                        error(response.status_code, response.json())
                    return response.json()
            except httpx.RequestError:
                pass
            if attempt < retries:
                log("http.retry", target=service)
                time.sleep(0.08)
        error(503, "Зависимый сервис временно недоступен.")
    finally:
        if breaker:
            breaker.finish(ok)
