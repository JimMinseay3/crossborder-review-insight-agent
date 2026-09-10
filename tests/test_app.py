import os
from pathlib import Path

os.environ["DATABASE_PATH"] = str(Path(__file__).parent / "test.db")
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_and_home():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_example_run_persists_and_exports():
    response = client.post("/api/runs", json={"example": "reviews.csv"})
    assert response.status_code == 200
    record = response.json()
    assert record["result"]["review_count"] == 12
    assert record["model_provider"] == "mock"
    assert client.get(f"/api/runs/{record['run_id']}").status_code == 200
    assert client.get(f"/api/runs/{record['run_id']}/export").status_code == 200


def test_rejects_bad_extension():
    response = client.post("/api/runs", json={"file_name": "reviews.txt", "file_content": "x"})
    assert response.status_code == 422

