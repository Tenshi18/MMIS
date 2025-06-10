from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import asyncio

from app.backend.dashboard import router as dashboard_router
from app.backend.db.database import init_db
from app.backend.rss_module.rss_eye import Settings, RSSEye

# Инициализация FastAPI
app = FastAPI(
    title="ИСМУ",
    description="API для мониторинга упоминаний Организации",
    version="0.1"
)

# Настройка CORS
origins = [
    "http://localhost:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Подключение роутеров
app.include_router(dashboard_router, prefix="/api")

# Монтирование статических файлов
app.mount("/static", StaticFiles(directory="app/frontend/static"), name="static")

@app.get("/")
async def root():
    return FileResponse("app/frontend/templates/index.html")

@app.on_event("startup")
async def startup_event():
    # Инициализация базы данных при запуске
    await init_db()
    
    # Запуск RSS-модуля
    config = Settings.from_json(os.getenv("RSS_EYE_JSON_CONFIG"))
    app.state.rss_eye = RSSEye(config)
    asyncio.create_task(app.state.rss_eye.run())

@app.on_event("shutdown")
async def shutdown_event():
    # Остановка RSS-модуля
    if hasattr(app.state, 'rss_eye'):
        app.state.rss_eye.shutdown_event.set()
        await app.state.rss_eye.close_session()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)