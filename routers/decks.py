import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Deck, DeckCard

router = APIRouter(prefix="/api/decks", tags=["decks"])

BASIC_LANDS = {
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
    "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
    "Snow-Covered Mountain", "Snow-Covered Forest",
}


# ── Schemas ──────────────────────────────────────────────────────────────────

class CardIn(BaseModel):
    card_name: str
    scryfall_id: str
    quantity: int = 1
    is_commander: bool = False
    usd_price: Optional[float] = None
    image_uri: Optional[str] = None
    type_line: Optional[str] = None
    color_identity: list[str] = []
    mana_cost: Optional[str] = None


class DeckIn(BaseModel):
    name: str
    commander_name: Optional[str] = None
    tagline: Optional[str] = None
    cards: list[CardIn] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deck_summary(deck: Deck, cards: list[DeckCard]) -> dict:
    total_price = sum((c.usd_price or 0) * c.quantity for c in cards)
    card_count = sum(c.quantity for c in cards)
    return {
        "id": deck.id,
        "name": deck.name,
        "commander_name": deck.commander_name,
        "card_count": card_count,
        "total_price": round(total_price, 2),
        "updated_at": deck.updated_at.isoformat(),
    }


def _card_out(c: DeckCard) -> dict:
    return {
        "card_name": c.card_name,
        "scryfall_id": c.scryfall_id,
        "quantity": c.quantity,
        "is_commander": c.is_commander,
        "usd_price": c.usd_price,
        "image_uri": c.image_uri,
        "type_line": c.type_line,
        "color_identity": json.loads(c.color_identity) if c.color_identity else [],
        "mana_cost": c.mana_cost,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_decks(session: Session = Depends(get_session)):
    decks = session.exec(select(Deck)).all()
    result = []
    for deck in decks:
        cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck.id)).all()
        result.append(_deck_summary(deck, cards))
    return sorted(result, key=lambda d: d["updated_at"], reverse=True)


@router.post("", status_code=201)
def create_deck(session: Session = Depends(get_session)):
    deck = Deck(name="New Deck")
    session.add(deck)
    session.commit()
    session.refresh(deck)
    return {"id": deck.id, "name": deck.name}


@router.get("/{deck_id}")
def get_deck(deck_id: int, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    return {
        "id": deck.id,
        "name": deck.name,
        "commander_name": deck.commander_name,
        "created_at": deck.created_at.isoformat(),
        "updated_at": deck.updated_at.isoformat(),
        "primer": deck.primer,
        "build_logic": deck.build_logic,
        "tagline": deck.tagline,
        "cards": [_card_out(c) for c in cards],
    }


@router.put("/{deck_id}")
def update_deck(deck_id: int, body: DeckIn, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

    deck.name = body.name
    deck.commander_name = body.commander_name
    deck.tagline = body.tagline
    deck.updated_at = datetime.utcnow()

    # Replace all cards
    existing = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    for c in existing:
        session.delete(c)

    for card in body.cards:
        session.add(
            DeckCard(
                deck_id=deck_id,
                card_name=card.card_name,
                scryfall_id=card.scryfall_id,
                quantity=card.quantity,
                is_commander=card.is_commander,
                usd_price=card.usd_price,
                image_uri=card.image_uri,
                type_line=card.type_line,
                color_identity=json.dumps(card.color_identity),
                mana_cost=card.mana_cost,
            )
        )

    session.commit()
    return {"success": True}


@router.delete("/{deck_id}")
def delete_deck(deck_id: int, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    for c in cards:
        session.delete(c)
    session.delete(deck)
    session.commit()
    return {"success": True}


@router.get("/{deck_id}/validate")
def validate_deck(deck_id: int, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    issues: list[str] = []

    total = sum(c.quantity for c in cards)
    if total != 100:
        issues.append(f"Deck has {total} cards — needs exactly 100.")

    commanders = [c for c in cards if c.is_commander]
    if not commanders:
        issues.append("No commander selected.")
    elif len(commanders) > 1:
        issues.append(
            f"{len(commanders)} cards marked as commander — maximum is 1 "
            "(use the partner mechanic if needed)."
        )

    # Duplicate check (basic lands exempt)
    name_counts: dict[str, int] = {}
    for c in cards:
        if c.card_name not in BASIC_LANDS:
            name_counts[c.card_name] = name_counts.get(c.card_name, 0) + c.quantity
    for name, count in name_counts.items():
        if count > 1:
            issues.append(f'"{name}" appears {count} times — max 1 copy for non-basic lands.')

    # Color identity check
    if commanders:
        cmd = commanders[0]
        cmd_identity = set(json.loads(cmd.color_identity) if cmd.color_identity else [])
        for c in cards:
            if c.is_commander:
                continue
            card_identity = set(json.loads(c.color_identity) if c.color_identity else [])
            if not card_identity.issubset(cmd_identity):
                outside = sorted(card_identity - cmd_identity)
                issues.append(
                    f'"{c.card_name}" has color identity {sorted(card_identity)} '
                    f"— {outside} outside commander's identity {sorted(cmd_identity)}."
                )

    return {"valid": len(issues) == 0, "issues": issues, "total_cards": total}


@router.get("/{deck_id}/export")
def export_deck(deck_id: int, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    commanders = sorted([c for c in cards if c.is_commander], key=lambda c: c.card_name)
    main = sorted([c for c in cards if not c.is_commander], key=lambda c: c.card_name)

    lines: list[str] = []
    if commanders:
        lines.append("Commander")
        for c in commanders:
            lines.append(f"1 {c.card_name}")
        lines.append("")

    lines.append("Deck")
    for c in main:
        lines.append(f"{c.quantity} {c.card_name}")

    total_price = sum((c.usd_price or 0) * c.quantity for c in cards)
    total_cards = sum(c.quantity for c in cards)
    lines.append("")
    lines.append(f"// {total_cards} cards  |  ${total_price:.2f} total")

    return {"text": "\n".join(lines)}
