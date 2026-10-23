import pytest


@pytest.mark.django_db
def test_healthz_reports_database_ok(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True}


def test_healthz_rejects_post(client):
    assert client.post("/healthz/").status_code == 405
