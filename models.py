from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship


class DeckCard(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    deck_id: int = Field(foreign_key="deck.id")
    card_name: str
    scryfall_id: str
    quantity: int = 1
    is_commander: bool = False
    usd_price: Optional[float] = None
    image_uri: Optional[str] = None
    type_line: Optional[str] = None
    color_identity: Optional[str] = None  # JSON-encoded list, e.g. '["W","U"]'
    mana_cost: Optional[str] = None

    deck: Optional["Deck"] = Relationship(back_populates="cards")


class Deck(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = "New Deck"
    commander_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    primer: Optional[str] = None
    build_logic: Optional[str] = None
    tagline: Optional[str] = None

    cards: List[DeckCard] = Relationship(back_populates="deck")
