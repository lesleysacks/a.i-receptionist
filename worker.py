#!/usr/bin/env python
"""RQ background-job worker entry point.

Run with:  python worker.py   (requires REDIS_URL)

Processes queued jobs such as owner notifications and booking reminders.
"""

from __future__ import annotations

import logging

from services.jobs import QUEUE_NAME, get_redis_connection
from services.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    connection = get_redis_connection()
    if connection is None:
        raise SystemExit("REDIS_URL must be set and reachable to run the worker.")
    from rq import Queue, Worker

    logger.info("Starting RQ worker on queue %s", QUEUE_NAME)
    worker = Worker([Queue(QUEUE_NAME, connection=connection)], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
