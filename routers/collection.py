from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import CollectionCard

router = APIRouter(prefix="/api/collection", tags=["collection"])
SCRYFALL = "https://api.scryfall.com"


class AddCardRequest(BaseModel):
    scryfall_id: str
    card_name: str
    quantity: int = 1
    image_uri: Optional[str] = None
    type_line: Optional[str] = None
    usd_price: Optional[float] = None
    mana_cost: Optional[str] = None
    color_identity: Optional[str] = None


class UpdateQuantityRequest(BaseModel):
    quantity: int


class ImportRequest(BaseModel):
    cards: list[dict]


@router.get("")
def list_collection(session: Session = Depends(get_session)):
    return session.exec(select(CollectionCard).order_by(CollectionCard.card_name)).all()


@router.post("", status_code=201)
def add_card(body: AddCardRequest, session: Session = Depends(get_session)):
    existing = session.exec(
        select(CollectionCard).where(CollectionCard.card_name == body.card_name)
    ).first()
    if existing:
        existing.quantity += body.quantity
        session.commit()
        session.refresh(existing)
        return existing
    card = CollectionCard(**body.model_dump())
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


@router.put("/{card_id}")
def update_card(card_id: int, body: UpdateQuantityRequest, session: Session = Depends(get_session)):
    card = session.get(CollectionCard, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    if body.quantity <= 0:
        session.delete(card)
        session.commit()
        return {"deleted": True}
    card.quantity = body.quantity
    session.commit()
    session.refresh(card)
    return card


@router.delete("/all", status_code=204)
def clear_collection(session: Session = Depends(get_session)):
    all_cards = session.exec(select(CollectionCard)).all()
    for card in all_cards:
        session.delete(card)
    session.commit()


@router.delete("/{card_id}", status_code=204)
def remove_card(card_id: int, session: Session = Depends(get_session)):
    card = session.get(CollectionCard, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    session.delete(card)
    session.commit()


@router.post("/import")
async def import_to_collection(body: ImportRequest, session: Session = Depends(get_session)):
    if not body.cards:
        return {"added": 0, "not_found": []}

    fetched = []
    not_found = []

    for i in range(0, len(body.cards), 75):
        batch = body.cards[i : i + 75]
        name_to_qty: dict[str, int] = {c["name"].lower(): c.get("quantity", 1) for c in batch}

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SCRYFALL}/cards/collection",
                json={"identifiers": [{"name": c["name"]} for c in batch]},
                timeout=30,
            )
        data = r.json()

        for card_data in data.get("data", []):
            qty = name_to_qty.get(card_data["name"].lower(), 1)
            if qty == 1:
                faces = card_data.get("card_faces", [])
                if faces:
                    qty = name_to_qty.get(faces[0].get("name", "").lower(), qty)

            image_uri = None
            if "image_uris" in card_data:
                image_uri = card_data["image_uris"].get("normal")
            elif card_data.get("card_faces") and "image_uris" in card_data["card_faces"][0]:
                image_uri = card_data["card_faces"][0]["image_uris"].get("normal")

            fetched.append({
                "scryfall_id": card_data["id"],
                "card_name": card_data["name"],
                "quantity": qty,
                "image_uri": image_uri,
                "type_line": card_data.get("type_line"),
                "usd_price": float(card_data.get("prices", {}).get("usd") or 0) or None,
                "mana_cost": card_data.get("mana_cost"),
                "color_identity": str(card_data.get("color_identity", [])),
            })

        for nf in data.get("not_found", []):
            not_found.append(nf.get("name", str(nf)))

    for c in fetched:
        existing = session.exec(
            select(CollectionCard).where(CollectionCard.card_name == c["card_name"])
        ).first()
        if existing:
            existing.quantity += c["quantity"]
        else:
            session.add(CollectionCard(**c))
    session.commit()

    return {"added": len(fetched), "not_found": not_found}
