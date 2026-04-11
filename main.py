import re
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

load_dotenv()

from database import create_db, engine
from models import Deck, DeckCard
from routers import cards, decks, ai

_TYPE_ORDER = ["Creature", "Planeswalker", "Instant", "Sorcery", "Enchantment", "Artifact", "Land", "Other"]


def _card_type(type_line: str) -> str:
    if not type_line:
        return "Other"
    for t in ["Creature", "Planeswalker", "Instant", "Sorcery", "Enchantment", "Artifact", "Land"]:
        if t in type_line:
            return t
    return "Other"


def _parse_mc(mana_cost: str) -> int:
    if not mana_cost:
        return 0
    cmc = 0
    for sym in re.findall(r"\{([^}]+)\}", mana_cost):
        if sym.isdigit():
            cmc += int(sym)
        elif sym != "X":
            cmc += 1
    return cmc


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
def home(request: Request):
    with Session(engine) as session:
        all_decks = session.exec(select(Deck)).all()
        deck_data = []
        for deck in all_decks:
            cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck.id)).all()
            commander = next((c for c in cards if c.is_commander), None)
            card_count = sum(c.quantity for c in cards)
            total_price = sum((c.usd_price or 0) * c.quantity for c in cards)
            deck_data.append({
                "id": deck.id,
                "name": deck.name,
                "commander_name": deck.commander_name,
                "commander_image": commander.image_uri if commander else None,
                "card_count": card_count,
                "total_price": round(total_price, 2),
                "tagline": deck.tagline,
                "updated_at": deck.updated_at,
                "share_token": deck.share_token,
            })
        deck_data.sort(key=lambda d: d["updated_at"], reverse=True)
    return templates.TemplateResponse(request, "home.html", {"decks": deck_data})


@app.get("/builder")
async def builder(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/share/{token}")
def share_view(token: str, request: Request):
    with Session(engine) as session:
        deck = session.exec(select(Deck).where(Deck.share_token == token)).first()
        if not deck:
            return templates.TemplateResponse(
                request, "share.html", {"deck": None}, status_code=404
            )

        all_cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck.id)).all()
        commander = next((c for c in all_cards if c.is_commander), None)
        main_cards = sorted([c for c in all_cards if not c.is_commander], key=lambda c: c.card_name)

        card_groups: dict[str, list] = {t: [] for t in _TYPE_ORDER}
        for card in main_cards:
            card_groups[_card_type(card.type_line)].append(card)

        card_count = sum(c.quantity for c in all_cards)
        total_price = sum((c.usd_price or 0) * c.quantity for c in all_cards)

        # Mana curve for non-land cards
        curve = [0] * 8
        nonland = [c for c in main_cards if _card_type(c.type_line) != "Land"]
        for card in nonland:
            curve[min(_parse_mc(card.mana_cost), 7)] += card.quantity
        total_nonland = sum(c.quantity for c in nonland)
        avg_cmc = (
            sum(_parse_mc(c.mana_cost) * c.quantity for c in nonland) / total_nonland
            if total_nonland else 0
        )

        # Group prices
        group_prices = {
            t: sum((c.usd_price or 0) * c.quantity for c in card_groups[t])
            for t in _TYPE_ORDER
        }

        return templates.TemplateResponse(
            request,
            "share.html",
            {
                "deck": deck,
                "commander": commander,
                "card_groups": card_groups,
                "type_order": _TYPE_ORDER,
                "group_prices": group_prices,
                "card_count": card_count,
                "total_price": round(total_price, 2),
                "curve": curve,
                "max_curve": max(curve) or 1,
                "avg_cmc": round(avg_cmc, 2),
            },
        )
