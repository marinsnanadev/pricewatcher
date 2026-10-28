from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth, insights, notifications, products, realtime

app = FastAPI(title="Price Watcher API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(notifications.router)
app.include_router(realtime.router)
app.include_router(insights.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
