# MTG Commander Deck Builder

A web app for building, managing, and analysing Magic: The Gathering Commander decks. Includes AI-powered deck generation, natural language editing, primers, and real-time pricing via Scryfall.

---

## Features

- **AI Deck Generation** — Describe a deck in plain English and have AI build a full 100-card Commander deck with pricing
- **AI Deck Editing** — Use natural language to modify an existing deck ("add more ramp", "replace weak creatures")
- **Deck Primer** — AI-generated playstyle guide and build logic for any deck
- **Witty Tagline** — AI-generated one-liner describing the deck's personality, editable and regeneratable
- **Real-time Pricing** — Card prices pulled live from Scryfall
- **Budget Tool** — Compare printings to find cheaper versions of cards
- **Deck Validation** — Checks card count, commander legality, color identity, and duplicates
- **Import / Export** — Compatible with Moxfield, Archidekt, TappedOut, MTGO, and Arena formats

---

## Tech Stack

- **Backend:** Python, FastAPI, SQLModel, SQLite
- **Frontend:** Alpine.js, Tailwind CSS
- **AI:** Google Gemini API
- **Card Data & Pricing:** Scryfall API

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/BARDONMAP/MtG-Deck-Creator.git
cd MtG-Deck-Creator
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Get a Gemini API key

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with your Google account
3. Click **Get API key** → **Create API key**
4. Copy the key

### 4. Configure your API key

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_api_key_here
```

### 5. Run the app

```bash
python -m uvicorn main:app --reload
```

Open your browser to [http://localhost:8000](http://localhost:8000)

---

## Usage

### Building a deck manually
1. Click **+ New Deck** in the sidebar
2. Search for cards in the right panel
3. Add cards and set your commander

### Generating a deck with AI
1. Click **✨ Generate with AI** in the sidebar
2. Describe the deck you want (strategy, budget, theme, etc.)
3. Click **✨ Generate Deck** and wait ~15 seconds
4. Click **Open Deck** to load it

### Editing a deck with AI
- Use the **✨ AI edit bar** above the deck list
- Type an instruction and press Enter or click **Apply**
- A summary of what changed appears below the bar

### Primer & Build Logic
- Click **📖 Primer** in the toolbar to generate or view the deck's playstyle guide and card choice explanations

### Tagline
- The italic line below the header shows the deck's tagline
- Click it to edit directly, or hover and click **✨** to regenerate with optional guidance

---

## Notes

- The Gemini free tier allows up to 500 requests/day
- Card prices are fetched live from Scryfall and may vary
- The `decks.db` file stores all your decks locally
- Never commit your `.env` file — it contains your API key
