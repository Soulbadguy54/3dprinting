import os

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from api.database import engine

app = FastAPI(
    title="RateApp API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/api/health")
def health() -> dict[str, object]:
    database_configured = engine is not None
    database_ok = False

    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database_ok = True
        except SQLAlchemyError:
            database_ok = False

    return {
        "ok": True,
        "service": "rateapp-api",
        "database": {
            "configured": database_configured,
            "reachable": database_ok,
        },
        "environment": os.getenv("VERCEL_ENV", "local"),
    }


@app.get("/api")
def api_root() -> dict[str, str]:
    return {
        "name": "RateApp API",
        "status": "ok",
        "docs": "/api/docs",
    }
