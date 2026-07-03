# app/main.py

from fastapi import FastAPI
from app.routers import chat, health

app = FastAPI()

app.include_router(chat.router)
app.include_router(health.router)

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}