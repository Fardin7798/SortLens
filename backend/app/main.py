"""FastAPI app. Runs only on localhost."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.jobs import router as jobs_router
from app.api.plans import router as plans_router
from app.core.config import settings
from app.db import store

app = FastAPI(title="SortLens", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs_router)
app.include_router(plans_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/stats")
def get_stats() -> dict[str, int]:
    con = store.connect(settings.db_path)
    try:
        return store.stats(con)
    finally:
        con.close()
