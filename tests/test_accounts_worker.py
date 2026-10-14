"""The SMTP worker owns fresh contexts and stops without printing link secrets."""
import threading

from criticard.db import get_db
from test_accounts import accounts_app


def test_worker_closes_each_database_context_and_stops(accounts_app, monkeypatch):
    from criticard.accounts import worker
    from criticard.accounts import mail
    stop = threading.Event()
    connections = []
    accounts_app.config.update(ACCOUNT_MAIL_BACKEND="smtp", ACCOUNT_BASE_URL="https://criticard.example",
                               ACCOUNT_MAIL_FROM="no-reply@criticard.example", ACCOUNT_SMTP_HOST="smtp.example")

    def deliver_batch(limit, stop_event=None):
        connections.append(get_db())
        if len(connections) == 2:
            stop.set()
        return {"sent": 0, "failed": 0, "discarded": 0}

    monkeypatch.setattr(mail, "send_pending", deliver_batch)
    monkeypatch.setattr(stop, "wait", lambda timeout: stop.is_set())
    assert worker.run_worker(accounts_app, stop, interval=10, batch_size=10) == 0
    assert len(connections) == 2
    assert connections[0] is not connections[1]
    assert all(database.connection.closed for database in connections)


def test_worker_refuses_local_file_transport(accounts_app):
    from criticard.accounts import worker
    assert worker.run_worker(accounts_app, threading.Event(), interval=10) == 2
