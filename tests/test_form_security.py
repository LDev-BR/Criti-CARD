from criticard import create_app
from conftest import post


def test_sensitive_forms_have_restrictive_headers(client):
    response = client.get("/")
    assert "script-src 'self'" in response.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_login_limit_is_persistent_and_ignores_forged_proxy_headers(app, client):
    app.config["LOGIN_ATTEMPT_LIMIT"] = 2
    for forwarded in ("1.2.3.4", "2.3.4.5"):
        assert post(client, "/", {"username": "alice", "senha": "incorrect"}, headers={"X-Forwarded-For": forwarded}).status_code == 200
    blocked = post(client, "/", {"username": "alice", "senha": "Password1!"})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    restarted = create_app(dict(app.config)).test_client()
    assert post(restarted, "/", {"username": "alice", "senha": "Password1!"}).status_code == 429


def test_limit_window_expires_without_locking_accounts(app, client, monkeypatch):
    import time
    clock = [time.time()]
    monkeypatch.setattr("time.time", lambda: clock[0])
    app.config.update(LOGIN_ATTEMPT_LIMIT=1, LOGIN_ATTEMPT_WINDOW=10)
    assert post(client, "/", {"username": "alice", "senha": "incorrect"}).status_code == 200
    assert post(client, "/", {"username": "alice", "senha": "Password1!"}).status_code == 429
    clock[0] += 11
    assert post(client, "/", {"username": "alice", "senha": "Password1!"}).status_code == 302


def test_multipart_cannot_supply_unbounded_number_of_fields(client):
    data = {"csrf_token": "invalid", **{f"field{i}": "x" for i in range(50)}}
    assert client.post("/cadastro", data=data, content_type="multipart/form-data").status_code == 413
