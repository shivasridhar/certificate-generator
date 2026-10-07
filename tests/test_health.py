def test_health_check_returns_200(client):
    """
    Verify that GET /health returns HTTP 200 and {'status': 'ok'}.
    Also exercises that the TestClient and in-memory test database fixture work properly.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
