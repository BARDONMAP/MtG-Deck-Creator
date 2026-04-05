from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter(prefix="/api/cards", tags=["cards"])

SCRYFALL = "https://api.scryfall.com"


async def scryfall_get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SCRYFALL}{path}", params=params, timeout=10)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Card not found")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Scryfall error")
    return r.json()


def _image_uri(card: dict) -> str | None:
    if "image_uris" in card:
        return card["image_uris"].get("normal")
    faces = card.get("card_faces", [])
    if faces and "image_uris" in faces[0]:
        return faces[0]["image_uris"].get("normal")
    return None


def _format_card(card: dict) -> dict:
    oracle = card.get("oracle_text", "")
    if not oracle:
        oracle = " // ".join(
            f.get("oracle_text", "") for f in card.get("card_faces", [])
        )
    mana_cost = card.get("mana_cost", "")
    if not mana_cost:
        mana_cost = " // ".join(
            f.get("mana_cost", "") for f in card.get("card_faces", [])
        )
    type_line = card.get("type_line", "")
    legalities = card.get("legalities", {})
    return {
        "id": card["id"],
        "name": card["name"],
        "type_line": type_line,
        "oracle_text": oracle,
        "mana_cost": mana_cost,
        "cmc": card.get("cmc", 0),
        "colors": card.get("colors", []),
        "color_identity": card.get("color_identity", []),
        "legalities": legalities,
        "prices": card.get("prices", {}),
        "image_uri": _image_uri(card),
        "set": card.get("set", ""),
        "set_name": card.get("set_name", ""),
        "rarity": card.get("rarity", ""),
        "is_commander_legal": legalities.get("commander") == "legal",
        "can_be_commander": (
            "Legendary" in type_line and "Creature" in type_line
        ) or "can be your commander" in oracle.lower(),
    }


@router.get("/autocomplete")
async def autocomplete(q: str):
    data = await scryfall_get("/cards/autocomplete", {"q": q})
    return {"names": data.get("data", [])[:15]}


@router.get("/named")
async def get_card_named(name: str):
    data = await scryfall_get("/cards/named", {"fuzzy": name})
    return _format_card(data)


@router.get("/search")
async def search_cards(q: str):
    try:
        data = await scryfall_get("/cards/search", {"q": q, "order": "name"})
        return {"cards": [_format_card(c) for c in data.get("data", [])[:20]]}
    except HTTPException as e:
        if e.status_code == 404:
            return {"cards": []}
        raise


@router.get("/printings")
async def get_printings(name: str):
    try:
        data = await scryfall_get(
            "/cards/search",
            {"q": f'!"{name}"', "unique": "prints", "order": "usd"},
        )
    except HTTPException as e:
        if e.status_code == 404:
            return {"printings": []}
        raise

    printings = []
    for c in data.get("data", []):
        usd = c.get("prices", {}).get("usd")
        if not usd:
            continue  # skip cards with no USD price
        printings.append(
            {
                "id": c["id"],
                "set": c.get("set", ""),
                "set_name": c.get("set_name", ""),
                "collector_number": c.get("collector_number", ""),
                "prices": c.get("prices", {}),
                "image_uri": _image_uri(c),
                "digital": c.get("digital", False),
                "promo": c.get("promo", False),
            }
        )
    return {"printings": printings}


class _ImportCard(BaseModel):
    name: str
    quantity: int = 1
    is_commander: bool = False


class _ImportRequest(BaseModel):
    cards: list[_ImportCard]


@router.post("/import")
async def import_cards(body: _ImportRequest):
    """
    Batch-fetch cards by name (for deck import).
    Uses Scryfall's collection endpoint, 75 cards per request.
    Returns formatted card objects (with prices) plus a list of names not found.
    """
    all_results: list[dict] = []
    all_not_found: list[str] = []

    for i in range(0, len(body.cards), 75):
        batch = body.cards[i : i + 75]
        name_to_meta = {c.name.lower(): c for c in batch}

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SCRYFALL}/cards/collection",
                json={"identifiers": [{"name": c.name} for c in batch]},
                timeout=30,
            )
        if r.status_code not in (200, 404):
            raise HTTPException(status_code=502, detail="Scryfall collection error")

        data = r.json()
        for card_data in data.get("data", []):
            # Match returned card back to the input entry by name (case-insensitive).
            # For double-faced cards, also try the front-face name.
            name_key = card_data["name"].lower()
            meta = name_to_meta.get(name_key)
            if not meta:
                faces = card_data.get("card_faces", [])
                if faces:
                    meta = name_to_meta.get(faces[0].get("name", "").lower())
            if not meta:
                meta = _ImportCard(name=card_data["name"])

            formatted = _format_card(card_data)
            formatted["quantity"] = meta.quantity
            formatted["is_commander"] = meta.is_commander
            all_results.append(formatted)

        for nf in data.get("not_found", []):
            # nf is the original identifier dict, e.g. {"name": "Bad Card Name"}
            all_not_found.append(nf.get("name", str(nf)))

    return {"cards": all_results, "not_found": all_not_found}


@router.post("/collection")
async def fetch_collection(identifiers: list[dict]):
    """Batch-fetch up to 75 cards by Scryfall ID for price refresh."""
    results = []
    for i in range(0, len(identifiers), 75):
        batch = identifiers[i : i + 75]
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SCRYFALL}/cards/collection",
                json={"identifiers": batch},
                timeout=15,
            )
        if r.status_code == 200:
            for card in r.json().get("data", []):
                results.append(
                    {
                        "id": card["id"],
                        "usd_price": float(card.get("prices", {}).get("usd") or 0) or None,
                        "image_uri": _image_uri(card),
                    }
                )
    return results
