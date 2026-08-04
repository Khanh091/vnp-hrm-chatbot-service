import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.answers import (
    AnswerContextBuilder,
    DeterministicAnswerFallback,
    FinalAnswerService,
    ToolResultSanitizer,
)
from app.api.routers.chat import router as chat_router
from app.api.routers.conversations import router as conversations_router
from app.api.routers.debug_routing import router as debug_routing_router
from app.api.routers.debug_tool_selection import (
    router as debug_tool_selection_router,
)
from app.api.routers.health import router as health_router
from app.api.schemas.common import ErrorResponse, ResponseMeta
from app.common.enums import ResponseCode
from app.common.exceptions import AppError
from app.config import Settings, get_settings
from app.context.conversation_service import ConversationService, ConversationStateError
from app.context.date_resolver import DateResolver
from app.context.dialog_manager import DialogTurnManager
from app.context.entity_memory import EntityMemoryService
from app.context.entity_resolver import BusinessEntityResolver, EntityResolver
from app.context.pending_action_service import PendingActionError, PendingActionService
from app.context.subject_resolver import (
    OdooSubjectLookupProvider,
    SubjectResolver,
)
from app.integrations.odoo.client import OdooClient
from app.integrations.odoo.exceptions import OdooError
from app.integrations.odoo.profile_schema import ProfileSchemaClient
from app.llm.client import (
    GroqLlmClient,
    OllamaLlmClient,
    build_llm_client,
)
from app.orchestration.context import GraphContext
from app.orchestration.graph import ChatGraphWorkflow
from app.orchestration.pipeline import ChatPipeline
from app.persistence.database import Database
from app.retrieval.embeddings import OllamaEmbeddingProvider
from app.retrieval.vector_store import DatabasePgVectorStore
from app.routing.argument_resolver import ArgumentResolver
from app.routing.candidate_retriever import CandidateRetriever
from app.routing.query_classifier import QueryClassifier
from app.routing.profile_target_resolver import ProfileTargetResolver
from app.routing.query_normalizer import QueryNormalizer
from app.routing.service import RoutingService
from app.routing.tool_selector import ToolSelector
from app.routing.validator import ToolSelectionValidator
from app.security.authorization import AuthorizationPolicyService
from app.tools import build_tool_registry
from app.tools.executor import ToolExecutor
from app.tools.response_formatter import ToolResponseFormatter
from app.workflows import build_workflow_registry
from app.workflows.slot_manager import SlotManager

logger = logging.getLogger("app.requests")


def _error_response(
    *,
    request: Request,
    code: ResponseCode,
    message: str,
    status_code: int,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        success=False,
        code=code,
        message=message,
        data=None,
        details=details or {},
        meta=ResponseMeta(request_id=request.state.request_id),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


def create_app(
    *,
    settings: Settings | None = None,
    odoo_client: OdooClient | None = None,
    routing_service: RoutingService | None = None,
    chat_pipeline: ChatPipeline | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        application.state.odoo_client = odoo_client or OdooClient(
            resolved_settings,
        )
        llm_client: OllamaLlmClient | GroqLlmClient | None = None
        selector_llm_client: OllamaLlmClient | GroqLlmClient | None = None
        final_answer_llm_client: OllamaLlmClient | GroqLlmClient | None = None
        embedding_provider: OllamaEmbeddingProvider | None = None
        database: Database | None = None
        checkpoint_context: object | None = None
        if chat_pipeline is not None:
            application.state.chat_pipeline = chat_pipeline
        else:
            registry = build_tool_registry()
            llm_client = build_llm_client(
                resolved_settings,
                purpose="classifier",
            )
            selector_llm_client = build_llm_client(
                resolved_settings,
                purpose="selector",
            )
            final_answer_llm_client = build_llm_client(
                resolved_settings,
                purpose="final_answer",
            )
            embedding_provider = OllamaEmbeddingProvider(resolved_settings)
            database = Database(resolved_settings.database_url)
            query_normalizer = QueryNormalizer()
            query_classifier = QueryClassifier(llm_client)
            candidate_retriever = CandidateRetriever(
                registry,
                embedding_provider,
                DatabasePgVectorStore(database),
            )
            resolved_routing = routing_service or RoutingService(
                query_normalizer,
                query_classifier,
                candidate_retriever,
                top_k=resolved_settings.tool_top_k,
                fetch_k=resolved_settings.tool_fetch_k,
                min_score=resolved_settings.tool_min_score,
            )
            selector = ToolSelector(
                selector_llm_client,
                registry,
                resolved_settings,
            )
            argument_resolver = ArgumentResolver()
            validator = ToolSelectionValidator(registry, resolved_settings)
            executor = ToolExecutor(registry, application.state.odoo_client)
            formatter = ToolResponseFormatter()
            answer_context_builder = AnswerContextBuilder(
                ToolResultSanitizer(
                    max_items=resolved_settings.max_final_answer_items,
                    max_chars=(
                        resolved_settings.max_final_answer_context_chars
                    ),
                )
            )
            final_answer_service = FinalAnswerService(
                final_answer_llm_client,
                DeterministicAnswerFallback(),
                temperature=resolved_settings.final_answer_temperature,
                max_tokens=resolved_settings.final_answer_max_tokens,
            )
            graph_context = GraphContext(
                query_normalizer=query_normalizer,
                query_classifier=query_classifier,
                profile_schema_client=ProfileSchemaClient(
                    application.state.odoo_client
                ),
                profile_target_resolver=ProfileTargetResolver(llm_client),
                candidate_retriever=candidate_retriever,
                tool_selector=selector,
                argument_resolver=argument_resolver,
                date_resolver=DateResolver(),
                dialog_turn_manager=DialogTurnManager(),
                entity_resolver=EntityResolver(),
                business_entity_resolver=BusinessEntityResolver(),
                subject_resolver=SubjectResolver(
                    OdooSubjectLookupProvider(application.state.odoo_client)
                ),
                entity_memory_service=EntityMemoryService(),
                validator=validator,
                authorization_policy=AuthorizationPolicyService(registry),
                tool_executor=executor,
                response_formatter=formatter,
                answer_context_builder=answer_context_builder,
                final_answer_service=final_answer_service,
                conversation_service=ConversationService(
                    database,
                    resolved_settings.conversation_state_ttl_seconds,
                ),
                pending_action_service=PendingActionService(
                    database,
                    resolved_settings.pending_action_ttl_seconds,
                    resolved_settings.pending_execution_lease_seconds,
                ),
                workflow_registry=build_workflow_registry(),
                slot_manager=SlotManager(),
                tool_registry=registry,
                settings=resolved_settings,
            )
            application.state.conversation_service = (
                graph_context.conversation_service
            )
            application.state.pending_action_service = (
                graph_context.pending_action_service
            )
            checkpointer = None
            try:
                from langgraph.checkpoint.postgres.aio import (
                    AsyncPostgresSaver,
                )

                checkpoint_url = (
                    resolved_settings.database_url.replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    )
                )
                os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
                checkpoint_context = (
                    AsyncPostgresSaver.from_conn_string(checkpoint_url)
                )
                checkpointer = await checkpoint_context.__aenter__()
                await checkpointer.setup()
            except Exception as error:
                logger.warning(
                    "langgraph_checkpointer_unavailable error=%s",
                    type(error).__name__,
                )
                if checkpoint_context is not None:
                    await checkpoint_context.__aexit__(  # type: ignore[attr-defined]
                        None, None, None
                    )
                    checkpoint_context = None
            application.state.routing_service = resolved_routing
            application.state.chat_pipeline = ChatGraphWorkflow(
                graph_context,
                checkpointer=checkpointer,
            )
        if resolved_settings.app_debug:
            if routing_service is not None:
                application.state.routing_service = routing_service
            elif not hasattr(application.state, "routing_service"):
                application.state.routing_service = (
                    application.state.chat_pipeline.routing_service
                )
        try:
            yield
        finally:
            if llm_client is not None:
                await llm_client.close()
            if selector_llm_client is not None:
                await selector_llm_client.close()
            if final_answer_llm_client is not None:
                await final_answer_llm_client.close()
            if embedding_provider is not None:
                await embedding_provider.close()
            if database is not None:
                await database.close()
            if checkpoint_context is not None:
                await checkpoint_context.__aexit__(None, None, None)  # type: ignore[attr-defined]
            if odoo_client is None:
                await cast(OdooClient, application.state.odoo_client).close()

    app = FastAPI(
        title="VNPT HRM Chatbot Service",
        version="0.1.0",
        debug=resolved_settings.app_debug,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            supplied_request_id
            if supplied_request_id and len(supplied_request_id) <= 128
            else str(uuid4())
        )
        request.state.request_id = request_id
        started_at = perf_counter()
        response: Response
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error request_id=%s endpoint=%s",
                request_id,
                request.url.path,
            )
            response = _error_response(
                request=request,
                code=ResponseCode.INTERNAL_ERROR,
                message="Internal server error",
                status_code=500,
            )
        response.headers["X-Request-ID"] = request_id
        latency_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "request_id=%s endpoint=%s status=%s latency_ms=%.2f",
            request_id,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        body = error.body if isinstance(error.body, dict) else {}
        structured = body.get("structured_answer")
        structured_data = structured if isinstance(structured, dict) else {}
        unknown_fields = sorted(
            str(item["loc"][-1])
            for item in error.errors()
            if item.get("type") == "extra_forbidden" and item.get("loc")
        )
        logger.warning(
            "request_validation_failed request_model=ChatRequest "
            "unknown_fields=%s structured_answer_type=%s slot_name=%s",
            unknown_fields,
            structured_data.get("type"),
            structured_data.get("slot_name"),
        )
        details: dict[str, object] = {
            "errors": [
                {
                    "location": ".".join(str(part) for part in item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ],
        }
        return _error_response(
            request=request,
            code=ResponseCode.INVALID_REQUEST,
            message="Request validation failed",
            status_code=422,
            details=details,
        )

    @app.exception_handler(AppError)
    async def app_exception_handler(
        request: Request,
        error: AppError,
    ) -> JSONResponse:
        if isinstance(error, OdooError):
            logger.warning(
                "Odoo request failed request_id=%s endpoint=%s odoo_error_code=%s",
                request.state.request_id,
                request.url.path,
                error.odoo_error_code or "CONNECTION_ERROR",
            )
        return _error_response(
            request=request,
            code=error.code,
            message=error.message,
            status_code=error.status_code,
            details=error.details,
        )

    @app.exception_handler(ConversationStateError)
    @app.exception_handler(PendingActionError)
    async def workflow_state_exception_handler(
        request: Request,
        error: ConversationStateError | PendingActionError,
    ) -> JSONResponse:
        code = ResponseCode(error.code)
        status_code = (
            404
            if error.code.endswith("_NOT_FOUND")
            else 403
            if error.code.endswith("_ACCESS_DENIED")
            else 410
            if error.code.endswith("_EXPIRED")
            else 409
        )
        return _error_response(
            request=request,
            code=code,
            message="Workflow state request could not be completed",
            status_code=status_code,
        )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    if resolved_settings.app_debug:
        app.include_router(debug_routing_router, prefix="/api/v1")
        app.include_router(debug_tool_selection_router, prefix="/api/v1")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    development_settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=development_settings.app_host,
        port=development_settings.app_port,
        reload=development_settings.app_debug,
    )
