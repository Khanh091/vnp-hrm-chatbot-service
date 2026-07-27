from fastapi import FastAPI

from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="VNPT HRM Chatbot Service",
        version="0.1.0",
    )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")

    return app


app = create_app()