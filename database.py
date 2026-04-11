from sqlalchemy import text
from sqlmodel import create_engine, SQLModel, Session

import os
DATABASE_URL = f"sqlite:///{os.getenv('DB_PATH', './decks.db')}"
engine = create_engine(DATABASE_URL, echo=False)


def create_db():
    SQLModel.metadata.create_all(engine)
    # Migrate: add new columns if they don't exist yet
    with engine.connect() as conn:
        for col in ("primer TEXT", "build_logic TEXT", "tagline TEXT", "share_token TEXT"):
            try:
                conn.execute(text(f"ALTER TABLE deck ADD COLUMN {col}"))
                conn.commit()
            except Exception:
                pass  # Column already exists


def get_session():
    with Session(engine) as session:
        yield session
