from typing import Any

from fastapi.testclient import TestClient

from app.integrations.odoo.schemas import OdooUserContext
from app.main import create_app
from app.routing.schemas import (
    Domain,
    Operation,
    QueryClassification,
    RouteType,
    RoutingDebugResult,
    RoutingStageTimings,
    ToolCandidate,
)
from tests.conftest import StubOdooClient, build_settings


class TrackingOdooClient(StubOdooClient):
    def __init__(self) -> None:
        super().__init__(build_settings())
        self.context_calls = 0

    async def get_current_user_context(
        self,
        *,
        odoo_user_id: int,
        request_id: str,
    ) -> OdooUserContext:
        self.context_calls += 1
        return await super().get_current_user_context(
            odoo_user_id=odoo_user_id,
            request_id=request_id,
        )


class FakeRoutingService:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def route(self, message: str) -> RoutingDebugResult:
        self.messages.append(message)
        return RoutingDebugResult(
            normalized_query="Tôi còn bao nhiêu ngày phép?",
            classification=QueryClassification(
                route_type=RouteType.STRUCTURED_QUERY,
                primary_domain=Domain.LEAVE,
                capability_hint="leave_balance",
                operation_hint=Operation.GET,
                confidence=0.97,
            ),
            candidates=[
                ToolCandidate(
                    tool_name="leave_get_balance",
                    domain=Domain.LEAVE,
                    capability="leave.balance",
                    operation=Operation.GET,
                    score=0.92,
                    rank=1,
                )
            ],
            timings=RoutingStageTimings(
                normalization_ms=0.1,
                classification_ms=2,
                embedding_ms=1,
                vector_search_ms=0.5,
            ),
        )


def test_debug_routing_endpoint_is_not_registered_in_production() -> None:
    settings = build_settings().model_copy(update={"app_debug": False})
    with TestClient(
        create_app(
            settings=settings,
            odoo_client=TrackingOdooClient(),
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
        )
    ) as client:
        response = client.post(
            "/api/v1/debug/routing",
            json={"message": "Tôi còn bao nhiêu ngày phép?"},
        )

    assert response.status_code == 404


def test_debug_routing_does_not_call_odoo_or_business_tool() -> None:
    settings = build_settings().model_copy(update={"app_debug": True})
    odoo_client = TrackingOdooClient()
    service = FakeRoutingService()
    with TestClient(
        create_app(
            settings=settings,
            odoo_client=odoo_client,
            routing_service=service,  # type: ignore[arg-type]
        )
    ) as client:
        response = client.post(
            "/api/v1/debug/routing",
            json={"message": "  Tôi còn bao nhiêu ngày phép?  "},
        )

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["classification"]["primary_domain"] == "leave"
    assert body["candidates"][0]["tool_name"] == "leave_get_balance"
    assert odoo_client.context_calls == 0
    assert service.messages == ["  Tôi còn bao nhiêu ngày phép?  "]
