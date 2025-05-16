from typing import Annotated, Union

from fastapi import FastAPI, Request, Header, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Инициализация FastAPI
app = FastAPI(
    title="ИСМУ",
    description="API для мониторинга упоминаний",
    version="0.1"
)

origins = [
    "http://localhost",
    "http://localhost:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/app/frontend", StaticFiles(directory="../frontend"), name="frontend")

templates = Jinja2Templates(directory="../frontend/templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/rss_results", response_class=HTMLResponse)
async def list_rss_results(request: Request, hx_request: Annotated[Union[str, None], Header()] = None):
    if hx_request:
        return templates.TemplateResponse("rss_results.html", {"request": request})
    return JSONResponse(content=jsonable_encoder({"Hello": "world"}))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
