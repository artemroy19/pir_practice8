import json
import logging
import os
import sys
import time

import pika

from .observability import REQUEST_ID, log

logging.getLogger("pika").setLevel(logging.WARNING)

QUEUE = "repit.attempt-updates"
KINDS = {"AttemptSubmitted", "AttemptReviewed"}


def connection():
    params = pika.URLParameters(os.environ["BROKER_URL"])
    params.socket_timeout = 3
    params.stack_timeout = 6
    params.blocked_connection_timeout = 5
    params.heartbeat = 30
    return pika.BlockingConnection(params)


def channel_for(link):
    channel = link.channel()
    channel.queue_declare(queue=QUEUE, durable=True)
    return channel


def publish(link):
    from .services.attempts import DB

    channel = channel_for(link)
    channel.confirm_delivery()
    while True:
        with DB.connect() as db:
            rows = db.all("SELECT * FROM outbox WHERE sent = 0 ORDER BY id LIMIT 20")
        for row in rows:
            marker = REQUEST_ID.set(row["correlation_id"])
            try:
                channel.basic_publish(exchange="", routing_key=QUEUE, body=row["payload"], mandatory=True,
                    properties=pika.BasicProperties(delivery_mode=2, message_id=f"attempts-{row['id']}",
                        correlation_id=row["correlation_id"], type=row["kind"], content_type="application/json"))
                with DB.connect(write=True) as db:
                    db.update("outbox", row["id"], {"sent": 1})
                log("event.published", event_id=f"attempts-{row['id']}", kind=row["kind"])
            finally:
                REQUEST_ID.reset(marker)
        link.process_data_events(time_limit=0.3)


def consume(link):
    from .services.catalog import record_attempt_event

    channel = channel_for(link)
    channel.basic_qos(prefetch_count=1)

    def handle(ch, method, properties, body):
        marker = REQUEST_ID.set(properties.correlation_id or "-")
        try:
            event = json.loads(body)
            if not properties.message_id or properties.type not in KINDS:
                raise ValueError("Неизвестный тип события")
            for key in ("test", "attempt", "student", "revision"):
                if type(event[key]) is not int or event[key] <= 0:
                    raise ValueError("Некорректный идентификатор")
            added = record_attempt_event(properties.message_id, properties.type, event)
            log("event.recorded" if added else "event.duplicate", event_id=properties.message_id,
                attempt=event["attempt"])
            ch.basic_ack(method.delivery_tag)
        except (ValueError, TypeError, KeyError):
            log("event.rejected", event_id=properties.message_id)
            ch.basic_reject(method.delivery_tag, requeue=False)
        except Exception as error:
            log("event.retry", error=type(error).__name__)
            link.sleep(2)
            ch.basic_nack(method.delivery_tag, requeue=True)
        finally:
            REQUEST_ID.reset(marker)

    channel.basic_consume(queue=QUEUE, on_message_callback=handle)
    channel.start_consuming()


def main():
    run = {"publish": publish, "consume": consume}[sys.argv[1]]
    while True:
        try:
            with connection() as link:
                run(link)
        except Exception as error:
            log("broker.reconnect", error=type(error).__name__)
            time.sleep(2)


if __name__ == "__main__":
    main()
