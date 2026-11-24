"""Publish a duplicate of the submitted event for an existing attempt."""

import argparse
import json

import pika

from repit.services.attempts import DB
from repit.broker import QUEUE, channel_for, connection

parser = argparse.ArgumentParser()
parser.add_argument("attempt", type=int)
args = parser.parse_args()
with DB.connect() as db:
    events = db.all("SELECT * FROM outbox WHERE kind = 'AttemptSubmitted' ORDER BY id DESC")
    original = next((item for item in events if json.loads(item["payload"])["attempt"] == args.attempt), None)
if original is None:
    parser.error("Событие сдачи не найдено")
with connection() as link:
    channel = channel_for(link)
    channel.confirm_delivery()
    for _ in range(2):
        channel.basic_publish(exchange="", routing_key=QUEUE, body=original["payload"], mandatory=True,
            properties=pika.BasicProperties(delivery_mode=2, message_id=f"attempts-{original['id']}",
                correlation_id=original["correlation_id"], type=original["kind"], content_type="application/json"))
