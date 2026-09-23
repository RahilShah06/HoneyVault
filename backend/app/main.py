"""Cloud HoneyVault API.

Start with:  uvicorn app.main:app --reload --port 8000   (from backend/)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.middleware import honeytoken_watch
from app.routes import activity, auth, dashboard, files

app = FastAPI(
    title="Cloud HoneyVault",
    description="Behaviour-based deception system for cloud storage (prototype).",
    version="0.1.0",
)

# Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Registered before the routers so it sees every request, including ones that
# never reach a route (bad auth, 404s) - a stolen credential being tried is
# most likely to show up on exactly those.
app.middleware("http")(honeytoken_watch)

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(activity.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def on_startup():
    # Creates tables if the DB file is new; seeding stays a separate explicit step.
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
