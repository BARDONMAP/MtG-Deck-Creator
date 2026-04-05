import json
import os
import re
from datetime import datetime
from typing import Optional

import httpx
from google import genai
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Deck, DeckCard

router = APIRouter(prefix="/api/ai", tags=["ai"])

SCRYFALL = "https://api.scryfall.com"

GENERATE_PROMPT = """\
You are an expert Magic: The Gathering Commander deck builder.

Build a complete 100-card Commander deck based on this description: "{description}"

Rules:
- Exactly 100 cards total: 1 commander + 99 other cards
- The commander must be a legendary creature or a card with "can be your commander"
- All cards must be legal in Commander format
- All non-commander cards must fit within the commander's color identity
- Include a solid mana base (~36-38 lands)
- Include mana ramp (Sol Ring, Arcane Signet, etc.)
- Include card draw and removal

Return ONLY valid JSON — no markdown, no explanation, nothing else:
{{
  "deck_name": "A fitting name for this deck",
  "commander": "Exact card name",
  "cards": [
    {{"name": "Card Name", "quantity": 1}},
    ...
  ],
  "primer": "2-3 paragraphs on how to play this deck and win conditions",
  "build_logic": "2-3 paragraphs on why these cards were chosen and key synergies",
  "tagline": "A single witty sentence (max 20 words) capturing the deck's personality"
}}

The commander must NOT appear in the cards array.
The cards array must sum to exactly 99 cards (counting quantities).
Basic lands may have quantity > 1.\
"""

TAGLINE_PROMPT = """\
Write a single witty, punchy tagline (max 20 words) for this Magic: The Gathering Commander deck.

Deck: "{deck_name}"
Commander: {commander}
Playstyle: {playstyle}
{guidance_line}
Be clever and capture the deck's personality — hint at how it makes opponents suffer, laugh, or despair. No quotes, no JSON, no explanation — just the tagline.\
"""

PRIMER_PROMPT = """\
You are an expert Magic: The Gathering player writing a Commander deck primer.

Deck: "{deck_name}"
Commander: {commander}

Cards:
{card_list}

Write a concise Commander primer with two sections:

PLAYSTYLE: 2-3 paragraphs describing how this deck plays, the win conditions, and what a typical game looks like.

BUILD LOGIC: 2-3 paragraphs explaining the card choices — why this commander, how the cards synergize, and the key combos or engines.

Return ONLY valid JSON — no markdown, no explanation:
{{"primer": "...", "build_logic": "..."}}\
"""

EDIT_PROMPT = """\
You are an expert Magic: The Gathering Commander deck builder.

Current deck: "{deck_name}"
Commander: {commander}

Current cards:
{card_list}

User instruction: "{instruction}"

Apply this change and return the complete updated 100-card deck as valid JSON — no markdown, no explanation, nothing else:
{{
  "change_summary": "A concise 2-4 sentence description of exactly what was changed and why",
  "cards": [
    {{"name": "Card Name", "quantity": 1, "is_commander": false}},
    ...
  ]
}}

Rules:
- Exactly 100 cards total
- The commander must be included with "is_commander": true
- All cards must be legal in Commander format
- All non-commander cards must match the commander's color identity
- Basic lands may have quantity > 1
- Use real, existing Magic: The Gathering card names\
"""


def _get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_key_here":
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY not configured. Add your key to the .env file.",
        )
    return genai.Client(api_key=api_key)


def _parse_json(raw: str) -> dict:
    """Parse JSON from Claude's response, stripping any markdown fences."""
    text = raw.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: grab first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise HTTPException(status_code=502, detail="AI returned invalid JSON. Please try again.")


async def _scryfall_import(cards_input: list[dict]) -> tuple[list[dict], list[str]]:
    """Batch-fetch cards from Scryfall. Returns (formatted_cards, not_found_names)."""
    all_results: list[dict] = []
    all_not_found: list[str] = []

    for i in range(0, len(cards_input), 75):
        batch = cards_input[i : i + 75]
        name_to_meta = {c["name"].lower(): c for c in batch}

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SCRYFALL}/cards/collection",
                json={"identifiers": [{"name": c["name"]} for c in batch]},
                timeout=30,
            )
        if r.status_code not in (200, 404):
            raise HTTPException(status_code=502, detail="Scryfall error while fetching cards")

        data = r.json()
        for card_data in data.get("data", []):
            name_key = card_data["name"].lower()
            meta = name_to_meta.get(name_key)
            if not meta:
                faces = card_data.get("card_faces", [])
                if faces:
                    meta = name_to_meta.get(faces[0].get("name", "").lower())
            if not meta:
                meta = {"name": card_data["name"], "quantity": 1, "is_commander": False}

            image_uri = None
            if "image_uris" in card_data:
                image_uri = card_data["image_uris"].get("normal")
            elif card_data.get("card_faces") and "image_uris" in card_data["card_faces"][0]:
                image_uri = card_data["card_faces"][0]["image_uris"].get("normal")

            all_results.append({
                "card_name": card_data["name"],
                "scryfall_id": card_data["id"],
                "quantity": meta.get("quantity", 1),
                "is_commander": meta.get("is_commander", False),
                "usd_price": float(card_data.get("prices", {}).get("usd") or 0) or None,
                "image_uri": image_uri,
                "type_line": card_data.get("type_line", ""),
                "color_identity": card_data.get("color_identity", []),
                "mana_cost": card_data.get("mana_cost", ""),
            })

        for nf in data.get("not_found", []):
            all_not_found.append(nf.get("name", str(nf)))

    return all_results, all_not_found


# ── Schemas ────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    description: str
    deck_name: Optional[str] = None


class EditRequest(BaseModel):
    instruction: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/generate", status_code=201)
async def generate_deck(body: GenerateRequest, session: Session = Depends(get_session)):
    client = _get_gemini_client()

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=GENERATE_PROMPT.format(description=body.description),
    )
    deck_data = _parse_json(response.text)

    commander_name: str = deck_data.get("commander", "")
    deck_name: str = body.deck_name or deck_data.get("deck_name", "Generated Deck")
    cards_input: list[dict] = deck_data.get("cards", [])

    all_cards_input = [
        {"name": commander_name, "quantity": 1, "is_commander": True}
    ] + [
        {"name": c["name"], "quantity": c.get("quantity", 1), "is_commander": False}
        for c in cards_input
    ]

    fetched_cards, not_found = await _scryfall_import(all_cards_input)

    primer = deck_data.get("primer") or None
    build_logic = deck_data.get("build_logic") or None
    tagline = deck_data.get("tagline") or None

    deck = Deck(name=deck_name, commander_name=commander_name, primer=primer, build_logic=build_logic, tagline=tagline)
    session.add(deck)
    session.commit()
    session.refresh(deck)

    for card in fetched_cards:
        session.add(DeckCard(
            deck_id=deck.id,
            card_name=card["card_name"],
            scryfall_id=card["scryfall_id"],
            quantity=card["quantity"],
            is_commander=card["is_commander"],
            usd_price=card["usd_price"],
            image_uri=card["image_uri"],
            type_line=card["type_line"],
            color_identity=json.dumps(card["color_identity"]),
            mana_cost=card["mana_cost"],
        ))
    session.commit()

    total_price = sum((c["usd_price"] or 0) * c["quantity"] for c in fetched_cards)
    total_cards = sum(c["quantity"] for c in fetched_cards)

    return {
        "deck_id": deck.id,
        "deck_name": deck_name,
        "commander": commander_name,
        "total_cards": total_cards,
        "total_price": round(total_price, 2),
        "not_found": not_found,
        "primer": primer,
        "build_logic": build_logic,
        "tagline": tagline,
    }


@router.post("/edit/{deck_id}")
async def edit_deck(deck_id: int, body: EditRequest, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    commander = next((c for c in cards if c.is_commander), None)

    card_lines = []
    for c in cards:
        prefix = "[COMMANDER] " if c.is_commander else ""
        qty = f"{c.quantity}x " if c.quantity > 1 else ""
        card_lines.append(f"- {prefix}{qty}{c.card_name} ({c.type_line or 'Unknown'})")

    client = _get_gemini_client()
    prompt = EDIT_PROMPT.format(
        deck_name=deck.name,
        commander=commander.card_name if commander else "None",
        card_list="\n".join(card_lines),
        instruction=body.instruction,
    )

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    result = _parse_json(response.text)

    cards_input = [
        {
            "name": c["name"],
            "quantity": c.get("quantity", 1),
            "is_commander": c.get("is_commander", False),
        }
        for c in result.get("cards", [])
    ]

    fetched_cards, not_found = await _scryfall_import(cards_input)

    existing = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    for c in existing:
        session.delete(c)

    new_commander_name = None
    for card in fetched_cards:
        if card["is_commander"]:
            new_commander_name = card["card_name"]
        session.add(DeckCard(
            deck_id=deck_id,
            card_name=card["card_name"],
            scryfall_id=card["scryfall_id"],
            quantity=card["quantity"],
            is_commander=card["is_commander"],
            usd_price=card["usd_price"],
            image_uri=card["image_uri"],
            type_line=card["type_line"],
            color_identity=json.dumps(card["color_identity"]),
            mana_cost=card["mana_cost"],
        ))

    deck.commander_name = new_commander_name or deck.commander_name
    deck.updated_at = datetime.utcnow()
    session.commit()

    total_price = sum((c["usd_price"] or 0) * c["quantity"] for c in fetched_cards)
    total_cards = sum(c["quantity"] for c in fetched_cards)

    return {
        "deck_id": deck_id,
        "total_cards": total_cards,
        "total_price": round(total_price, 2),
        "not_found": not_found,
        "change_summary": result.get("change_summary", ""),
    }


@router.post("/primer/{deck_id}")
async def generate_primer(deck_id: int, session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    commander = next((c for c in cards if c.is_commander), None)

    card_lines = []
    for c in cards:
        prefix = "[COMMANDER] " if c.is_commander else ""
        qty = f"{c.quantity}x " if c.quantity > 1 else ""
        card_lines.append(f"- {prefix}{qty}{c.card_name} ({c.type_line or 'Unknown'})")

    client = _get_gemini_client()
    prompt = PRIMER_PROMPT.format(
        deck_name=deck.name,
        commander=commander.card_name if commander else "None",
        card_list="\n".join(card_lines),
    )

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    result = _parse_json(response.text)

    deck.primer = result.get("primer") or deck.primer
    deck.build_logic = result.get("build_logic") or deck.build_logic
    deck.updated_at = datetime.utcnow()
    session.commit()

    return {"primer": deck.primer, "build_logic": deck.build_logic}


class TaglineRequest(BaseModel):
    guidance: Optional[str] = None


@router.post("/tagline/{deck_id}")
async def generate_tagline(deck_id: int, body: TaglineRequest = TaglineRequest(), session: Session = Depends(get_session)):
    deck = session.get(Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

    cards = session.exec(select(DeckCard).where(DeckCard.deck_id == deck_id)).all()
    commander = next((c for c in cards if c.is_commander), None)

    playstyle = deck.primer or ", ".join(
        c.card_name for c in cards[:20] if not c.is_commander
    )
    guidance_line = f'Additional guidance: "{body.guidance}"' if body.guidance else ""

    client = _get_gemini_client()
    prompt = TAGLINE_PROMPT.format(
        deck_name=deck.name,
        commander=commander.card_name if commander else "None",
        playstyle=playstyle[:800],
        guidance_line=guidance_line,
    )

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    tagline = response.text.strip().strip('"').strip("'")

    deck.tagline = tagline
    deck.updated_at = datetime.utcnow()
    session.commit()

    return {"tagline": tagline}
