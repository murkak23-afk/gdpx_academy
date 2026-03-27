from fastapi.testclient import TestClient

from src.api.app import create_app


def test_health_and_health_live_return_ok() -> None:
    app = create_app()
    client = TestClient(app)
    for path in ("/health", "/health/live"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
