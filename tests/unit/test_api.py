from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["code"] == "SUCCESS"
    assert response.json()["message"] == "Chatbot service is available"
    assert response.json()["data"] == {
        "service": "vnpt-hrm-chatbot-service",
        "version": "0.1.0",
    }


def test_chat_rejects_empty_message(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "", "user_context": {"odoo_user_id": 2}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_chat_rejects_too_long_message(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "x" * 4001, "user_context": {"odoo_user_id": 2}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_request_id_is_in_response(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "test-request-id"},
    )

    assert response.headers["X-Request-ID"] == "test-request-id"
    assert response.json()["meta"]["request_id"] == "test-request-id"
