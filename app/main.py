from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(title="Mailwise API")
app.include_router(router)

@app.get("/")
def root():
    return {"status": "Mailwise API is running"}