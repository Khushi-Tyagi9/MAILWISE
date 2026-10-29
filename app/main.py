from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.routes import router
from app.db.session import ensure_schema

@asynccontextmanager
async def lifespan(app):
    ensure_schema()
    yield

app = FastAPI(title="Mailwise API", lifespan=lifespan)
app.include_router(router)

@app.get("/")
def root():
    return {"status": "Mailwise API is running"}
