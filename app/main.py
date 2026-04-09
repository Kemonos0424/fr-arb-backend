"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.api import auth, keys, settings as settings_api, dashboard, scan, trade


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev convenience; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="FR Arbitrage Web",
    description="Funding Rate arbitrage trading platform",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

origins = [o.strip() for o in settings.frontend_url.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(settings_api.router)
app.include_router(dashboard.router)
app.include_router(scan.router)
app.include_router(trade.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
