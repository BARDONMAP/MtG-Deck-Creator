from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from database import create_db
from routers import cards, decks, ai


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    yield


app = FastAPI(title="MTG Commander Deck Builder", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(cards.router)
app.include_router(decks.router)
app.include_router(ai.router)


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(request, "index.html")
