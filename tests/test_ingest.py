from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

VALID_LEAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "phone": "5125550123",
    "zip": "78701",
    "consent": True,
    "gdpr_consent": True
}

INVALID_LEAD = {
    "name": "",
    "email": "bad",
    "phone": "",
    "zip": "123",
    "consent": False
}


def test_ingest_success():
    response = client.post("/api/leads", json=VALID_LEAD)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["message"] == "Lead validated and queued"


def test_ingest_missing_consent():
    payload = VALID_LEAD.copy()
    payload["consent"] = False
    response = client.post("/api/leads", json=payload)
    assert response.status_code == 400


def test_ingest_invalid_payload():
    response = client.post("/api/leads", json=INVALID_LEAD)
    assert response.status_code == 422
