from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="AI Food API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from auth.router import router as auth_router
from chat.router import router as chat_router
from meal_planner.router import router as meal_planner_router
from profile_api.router import router as profile_router
from recognition.router import router as recognition_router
from users.router import router as users_router

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(meal_planner_router)
app.include_router(profile_router)
app.include_router(recognition_router)
app.include_router(users_router)

@app.get("/")
async def root():
    return {"status": "AI Food API running"}
