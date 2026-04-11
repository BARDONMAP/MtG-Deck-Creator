document.addEventListener("alpine:init", () => {
  Alpine.data("deckBuilder", () => ({
    // ── State ──────────────────────────────────────────────────────────────
    savedDecks: [],
    currentDeck: null, // { id, name, commander_name, cards: [...] }

    searchQuery: "",
    autocompleteResults: [],
    showAutocomplete: false,
    isSearching: false,
    selectedCard: null,
    searchDebounceTimer: null,

    saveStatus: "saved", // 'saved' | 'unsaved' | 'saving' | 'error'
    saveTimer: null,

    // Modals
    showBudgetModal: false,
    budgetCardName: "",
    budgetCurrentId: "",
    budgetPrintings: [],
    budgetLoading: false,

    showValidationModal: false,
    validationResult: null,

    showExportModal: false,
    exportText: "",
    exportCopied: false,

    // Import modal
    showImportModal: false,
    importText: "",
    importParsed: [],   // [{name, quantity, is_commander}] — live parse preview
    importStatus: "idle", // "idle" | "fetching" | "done" | "error"
    importResult: null, // {cards, not_found} from backend
    importMode: "replace", // "replace" | "new"

    // Tagline
    taglineEditing: false,
    taglineGenerating: false,
    showTaglineRegen: false,
    taglineGuidance: "",

    // Primer modal
    showPrimerModal: false,
    primerLoading: false,

    // AI Generate modal
    showGenerateModal: false,
    generateDescription: "",
    generateDeckName: "",
    generateStatus: "idle", // "idle" | "generating" | "done" | "error"
    generateError: "",
    generateResult: null, // {deck_id, deck_name, commander, total_cards, total_price, not_found}

    // AI Edit toolbar
    aiEditInstruction: "",
    aiEditStatus: "idle", // "idle" | "editing" | "done" | "error"
    aiEditMessage: "",
    aiEditSummary: "",

    // Hover card tooltip
    hoverCard: null,
    hoverStyle: "",
    hoverTimer: null,

    // Right panel tab
    rightPanel: "search", // 'search' | 'stats'

    // Share modal
    showShareModal: false,
    shareUrl: "",
    shareCopied: false,
    shareLoading: false,

    // Card preview enhancements
    cardRulings: null,       // null = not fetched, [] = fetched empty, [...] = fetched with rulings
    cardRulingsLoading: false,
    showRulings: false,
    similarCards: [],
    similarCardsLoading: false,

    FORMATS: [
      { key: "standard",  label: "Standard"  },
      { key: "pioneer",   label: "Pioneer"   },
      { key: "modern",    label: "Modern"    },
      { key: "legacy",    label: "Legacy"    },
      { key: "commander", label: "Commander" },
      { key: "pauper",    label: "Pauper"    },
    ],

    BASIC_LANDS: new Set([
      "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
      "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
      "Snow-Covered Mountain", "Snow-Covered Forest",
    ]),

    TYPE_ORDER: ["Creature", "Planeswalker", "Instant", "Sorcery", "Enchantment", "Artifact", "Land", "Other"],

    // ── Init ───────────────────────────────────────────────────────────────
    async init() {
      await this.fetchSavedDecks();
      if (this.savedDecks.length > 0) {
        await this.loadDeck(this.savedDecks[0].id);
      } else {
        await this.createNewDeck();
      }
    },

    // ── Deck management ────────────────────────────────────────────────────
    async fetchSavedDecks() {
      const r = await fetch("/api/decks");
      this.savedDecks = await r.json();
    },

    async createNewDeck() {
      const r = await fetch("/api/decks", { method: "POST" });
      const data = await r.json();
      this.currentDeck = { id: data.id, name: "New Deck", commander_name: null, cards: [] };
      await this.fetchSavedDecks();
    },

    async loadDeck(id) {
      const r = await fetch(`/api/decks/${id}`);
      this.currentDeck = await r.json();
    },

    async saveDeck() {
      if (!this.currentDeck?.id) return;
      this.saveStatus = "saving";
      try {
        const r = await fetch(`/api/decks/${this.currentDeck.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: this.currentDeck.name,
            commander_name: this.currentDeck.commander_name,
            tagline: this.currentDeck.tagline ?? null,
            cards: this.currentDeck.cards,
          }),
        });
        if (!r.ok) throw new Error();
        this.saveStatus = "saved";
        await this.fetchSavedDecks();
      } catch {
        this.saveStatus = "error";
      }
    },

    triggerSave() {
      this.saveStatus = "unsaved";
      clearTimeout(this.saveTimer);
      this.saveTimer = setTimeout(() => this.saveDeck(), 1200);
    },

    async deleteDeck(id) {
      if (!confirm("Delete this deck? This cannot be undone.")) return;
      await fetch(`/api/decks/${id}`, { method: "DELETE" });
      if (this.currentDeck?.id === id) this.currentDeck = null;
      await this.fetchSavedDecks();
      if (this.savedDecks.length > 0) {
        await this.loadDeck(this.savedDecks[0].id);
      } else {
        await this.createNewDeck();
      }
    },

    // ── Search ─────────────────────────────────────────────────────────────
    onSearchInput() {
      clearTimeout(this.searchDebounceTimer);
      if (this.searchQuery.length < 2) {
        this.autocompleteResults = [];
        this.showAutocomplete = false;
        return;
      }
      this.showAutocomplete = true;
      this.searchDebounceTimer = setTimeout(async () => {
        const r = await fetch(`/api/cards/autocomplete?q=${encodeURIComponent(this.searchQuery)}`);
        const data = await r.json();
        this.autocompleteResults = data.names;
        this.showAutocomplete = this.autocompleteResults.length > 0;
      }, 300);
    },

    async selectCardByName(name) {
      this.searchQuery = name;
      this.showAutocomplete = false;
      this.autocompleteResults = [];
      this.isSearching = true;
      this.selectedCard = null;
      this.cardRulings = null;
      this.showRulings = false;
      this.similarCards = [];
      try {
        const r = await fetch(`/api/cards/named?name=${encodeURIComponent(name)}`);
        if (r.ok) {
          this.selectedCard = await r.json();
          this.fetchSimilarCards(this.selectedCard.id);
        }
      } finally {
        this.isSearching = false;
      }
    },

    clearSearch() {
      this.searchQuery = "";
      this.autocompleteResults = [];
      this.showAutocomplete = false;
    },

    // ── Deck operations ────────────────────────────────────────────────────
    addCard(card) {
      if (!this.currentDeck || !card) return;
      const isBasic = this.BASIC_LANDS.has(card.name);
      const existing = this.currentDeck.cards.find(
        (c) => c.card_name === card.name && !c.is_commander
      );
      if (existing) {
        if (isBasic) existing.quantity++;
        // non-basic already present — no-op
      } else {
        this.currentDeck.cards.push({
          card_name: card.name,
          scryfall_id: card.id,
          quantity: 1,
          is_commander: false,
          usd_price: parseFloat(card.prices?.usd) || null,
          image_uri: card.image_uri,
          type_line: card.type_line,
          color_identity: card.color_identity ?? [],
          mana_cost: card.mana_cost,
        });
      }
      this.triggerSave();
    },

    setAsCommander(card) {
      if (!this.currentDeck || !card) return;
      // Remove any existing commander entry
      this.currentDeck.cards = this.currentDeck.cards.filter((c) => !c.is_commander);
      this.currentDeck.cards.unshift({
        card_name: card.name,
        scryfall_id: card.id,
        quantity: 1,
        is_commander: true,
        usd_price: parseFloat(card.prices?.usd) || null,
        image_uri: card.image_uri,
        type_line: card.type_line,
        color_identity: card.color_identity ?? [],
        mana_cost: card.mana_cost,
      });
      this.currentDeck.commander_name = card.name;
      this.triggerSave();
    },

    removeCard(cardName, isCommander = false) {
      if (!this.currentDeck) return;
      this.currentDeck.cards = this.currentDeck.cards.filter(
        (c) => !(c.card_name === cardName && c.is_commander === isCommander)
      );
      if (isCommander) this.currentDeck.commander_name = null;
      this.triggerSave();
    },

    updateQuantity(card, delta) {
      card.quantity = Math.max(1, card.quantity + delta);
      this.triggerSave();
    },

    async refreshPrices() {
      if (!this.currentDeck?.cards.length) return;
      const identifiers = this.currentDeck.cards.map((c) => ({ id: c.scryfall_id }));
      const r = await fetch("/api/cards/collection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(identifiers),
      });
      const updated = await r.json();
      for (const u of updated) {
        const card = this.currentDeck.cards.find((c) => c.scryfall_id === u.id);
        if (card) {
          card.usd_price = u.usd_price;
          if (u.image_uri) card.image_uri = u.image_uri;
        }
      }
      this.triggerSave();
    },

    // ── Computed ────────────────────────────────────────────────────────────
    get commander() {
      return this.currentDeck?.cards.find((c) => c.is_commander) ?? null;
    },

    get commanderColorIdentity() {
      return this.commander?.color_identity ?? [];
    },

    get totalCards() {
      return this.currentDeck?.cards.reduce((s, c) => s + c.quantity, 0) ?? 0;
    },

    get totalPrice() {
      return this.currentDeck?.cards.reduce((s, c) => s + (c.usd_price ?? 0) * c.quantity, 0) ?? 0;
    },

    getCardType(typeLine) {
      if (!typeLine) return "Other";
      if (typeLine.includes("Creature")) return "Creature";
      if (typeLine.includes("Planeswalker")) return "Planeswalker";
      if (typeLine.includes("Instant")) return "Instant";
      if (typeLine.includes("Sorcery")) return "Sorcery";
      if (typeLine.includes("Enchantment")) return "Enchantment";
      if (typeLine.includes("Artifact")) return "Artifact";
      if (typeLine.includes("Land")) return "Land";
      return "Other";
    },

    get cardsByType() {
      if (!this.currentDeck) return {};
      const groups = {};
      for (const t of this.TYPE_ORDER) groups[t] = [];
      for (const card of this.currentDeck.cards) {
        if (card.is_commander) continue;
        const t = this.getCardType(card.type_line);
        groups[t].push(card);
      }
      for (const t of this.TYPE_ORDER) {
        groups[t].sort((a, b) => a.card_name.localeCompare(b.card_name));
      }
      return groups;
    },

    groupTotal: (cards) => cards.reduce((s, c) => s + c.quantity, 0),
    groupPrice: (cards) => cards.reduce((s, c) => s + (c.usd_price ?? 0) * c.quantity, 0),

    isInDeck(name) {
      return this.currentDeck?.cards.some((c) => c.card_name === name && !c.is_commander) ?? false;
    },

    isCommander(name) {
      return this.currentDeck?.cards.some((c) => c.card_name === name && c.is_commander) ?? false;
    },

    // ── Budget modal ────────────────────────────────────────────────────────
    async openBudgetModal(card) {
      this.budgetCardName = card.card_name;
      this.budgetCurrentId = card.scryfall_id;
      this.budgetPrintings = [];
      this.budgetLoading = true;
      this.showBudgetModal = true;
      try {
        const r = await fetch(`/api/cards/printings?name=${encodeURIComponent(card.card_name)}`);
        const data = await r.json();
        this.budgetPrintings = data.printings;
      } finally {
        this.budgetLoading = false;
      }
    },

    switchPrinting(printing) {
      const card = this.currentDeck?.cards.find((c) => c.card_name === this.budgetCardName);
      if (!card) return;
      card.scryfall_id = printing.id;
      card.usd_price = parseFloat(printing.prices.usd) || null;
      if (printing.image_uri) card.image_uri = printing.image_uri;
      this.budgetCurrentId = printing.id;
      this.triggerSave();
    },

    // ── Validation modal ────────────────────────────────────────────────────
    async validateDeck() {
      if (!this.currentDeck?.id) return;
      await this.saveDeck(); // ensure DB is current before validating
      const r = await fetch(`/api/decks/${this.currentDeck.id}/validate`);
      this.validationResult = await r.json();
      this.showValidationModal = true;
    },

    // ── Export modal ────────────────────────────────────────────────────────
    async exportDeck() {
      if (!this.currentDeck?.id) return;
      await this.saveDeck();
      const r = await fetch(`/api/decks/${this.currentDeck.id}/export`);
      const data = await r.json();
      this.exportText = data.text;
      this.exportCopied = false;
      this.showExportModal = true;
    },

    async copyExport() {
      await navigator.clipboard.writeText(this.exportText);
      this.exportCopied = true;
      setTimeout(() => (this.exportCopied = false), 2000);
    },

    // ── Import modal ────────────────────────────────────────────────────────
    openImportModal() {
      this.importText = "";
      this.importParsed = [];
      this.importStatus = "idle";
      this.importResult = null;
      this.importMode = "replace";
      this.showImportModal = true;
    },

    onImportTextChange() {
      this.importParsed = this.parseDecklist(this.importText);
      // Reset result if the user edits after a successful fetch
      if (this.importStatus === "done") {
        this.importStatus = "idle";
        this.importResult = null;
      }
    },

    /**
     * Parse a plain-text deck list into [{name, quantity, is_commander}].
     * Handles formats from Moxfield, Archidekt, TappedOut, MTGO, Arena, etc.
     */
    parseDecklist(text) {
      // Matches "1 Card Name" or "1x Card Name"
      const CARD_RE = /^(\d+)x?\s+(.+)$/;
      // Section headers to skip (with optional trailing count like "(99)")
      const SECTION_RE = /^(Commander|Deck|Main\s*Deck?|Sideboard|Maybeboard|Companion|Lands?|Creatures?|Instants?|Sorceries|Enchantments?|Artifacts?|Planeswalkers?|Other|About)\s*(\(\d+\))?$/i;

      const seen = new Map(); // name.lower() → entry
      let inCommanderSection = false;

      for (const raw of text.split("\n")) {
        const line = raw.trim();
        if (!line || line.startsWith("//") || line.startsWith("#")) continue;

        if (SECTION_RE.test(line)) {
          inCommanderSection = /^commander/i.test(line);
          continue;
        }

        const match = line.match(CARD_RE);
        if (!match) continue;

        const qty = parseInt(match[1], 10);
        const name = match[2].trim();
        // Skip artifact lines like "100 cards"
        if (/^cards?$/i.test(name)) continue;

        const key = name.toLowerCase();
        if (seen.has(key)) {
          seen.get(key).quantity += qty;
        } else {
          seen.set(key, { name, quantity: qty, is_commander: inCommanderSection });
        }
      }

      return Array.from(seen.values());
    },

    get importCommanderName() {
      return this.importParsed.find((c) => c.is_commander)?.name ?? null;
    },

    async fetchImportPrices() {
      if (!this.importParsed.length) return;
      this.importStatus = "fetching";
      this.importResult = null;
      try {
        const r = await fetch("/api/cards/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cards: this.importParsed }),
        });
        if (!r.ok) throw new Error();
        this.importResult = await r.json();
        this.importStatus = "done";
      } catch {
        this.importStatus = "error";
      }
    },

    async applyImport() {
      if (!this.importResult?.cards?.length) return;

      const cards = this.importResult.cards.map((c) => ({
        card_name: c.name,
        scryfall_id: c.id,
        quantity: c.quantity,
        is_commander: c.is_commander,
        usd_price: parseFloat(c.prices?.usd) || null,
        image_uri: c.image_uri,
        type_line: c.type_line,
        color_identity: c.color_identity ?? [],
        mana_cost: c.mana_cost,
      }));

      const commanderCard = cards.find((c) => c.is_commander);

      if (this.importMode === "new") {
        const r = await fetch("/api/decks", { method: "POST" });
        const data = await r.json();
        this.currentDeck = {
          id: data.id,
          name: commanderCard ? `${commanderCard.card_name} Commander` : "Imported Deck",
          commander_name: commanderCard?.card_name ?? null,
          cards,
        };
      } else {
        this.currentDeck.cards = cards;
        this.currentDeck.commander_name = commanderCard?.card_name ?? null;
      }

      this.showImportModal = false;
      this.triggerSave();
      await this.fetchSavedDecks();
    },

    // ── Tagline ────────────────────────────────────────────────────────────
    async generateTagline() {
      if (!this.currentDeck?.id) return;
      this.taglineGenerating = true;
      try {
        const r = await fetch(`/api/ai/tagline/${this.currentDeck.id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ guidance: this.taglineGuidance.trim() || null }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || "Failed");
        const data = await r.json();
        this.currentDeck.tagline = data.tagline;
        this.taglineGuidance = "";
        this.showTaglineRegen = false;
        this.triggerSave();
      } finally {
        this.taglineGenerating = false;
      }
    },

    // ── Primer modal ───────────────────────────────────────────────────────
    async openPrimerModal() {
      this.showPrimerModal = true;
      if (!this.currentDeck?.primer && !this.primerLoading) {
        await this.generatePrimer();
      }
    },

    async generatePrimer() {
      if (!this.currentDeck?.id) return;
      this.primerLoading = true;
      try {
        const r = await fetch(`/api/ai/primer/${this.currentDeck.id}`, { method: "POST" });
        if (!r.ok) throw new Error((await r.json()).detail || "Failed");
        const data = await r.json();
        this.currentDeck.primer = data.primer;
        this.currentDeck.build_logic = data.build_logic;
      } finally {
        this.primerLoading = false;
      }
    },

    // ── AI Generate ────────────────────────────────────────────────────────
    openGenerateModal() {
      this.generateDescription = "";
      this.generateDeckName = "";
      this.generateStatus = "idle";
      this.generateError = "";
      this.generateResult = null;
      this.showGenerateModal = true;
    },

    async generateDeck() {
      if (!this.generateDescription.trim()) return;
      this.generateStatus = "generating";
      this.generateResult = null;
      this.generateError = "";
      try {
        const r = await fetch("/api/ai/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            description: this.generateDescription,
            deck_name: this.generateDeckName.trim() || null,
          }),
        });
        if (!r.ok) {
          const err = await r.json();
          throw new Error(err.detail || "Generation failed");
        }
        this.generateResult = await r.json();
        this.generateStatus = "done";
      } catch (e) {
        this.generateStatus = "error";
        this.generateError = e.message;
      }
    },

    async openGeneratedDeck() {
      if (!this.generateResult?.deck_id) return;
      this.showGenerateModal = false;
      await this.fetchSavedDecks();
      await this.loadDeck(this.generateResult.deck_id);
    },

    // ── AI Edit ────────────────────────────────────────────────────────────
    async submitAiEdit() {
      if (!this.aiEditInstruction.trim() || !this.currentDeck?.id) return;
      this.aiEditStatus = "editing";
      this.aiEditMessage = "";
      this.aiEditSummary = "";
      try {
        await this.saveDeck();
        const r = await fetch(`/api/ai/edit/${this.currentDeck.id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction: this.aiEditInstruction }),
        });
        if (!r.ok) {
          const err = await r.json();
          throw new Error(err.detail || "Edit failed");
        }
        const result = await r.json();
        await this.loadDeck(this.currentDeck.id);
        await this.fetchSavedDecks();
        const notFoundNote = result.not_found?.length
          ? ` · ${result.not_found.length} card${result.not_found.length > 1 ? "s" : ""} not found`
          : "";
        this.aiEditStatus = "done";
        this.aiEditMessage = `${result.total_cards} cards · $${result.total_price.toFixed(2)}${notFoundNote}`;
        this.aiEditSummary = result.change_summary || "";
        this.aiEditInstruction = "";
      } catch (e) {
        this.aiEditStatus = "error";
        this.aiEditMessage = e.message;
        setTimeout(() => { this.aiEditStatus = "idle"; this.aiEditMessage = ""; this.aiEditSummary = ""; }, 6000);
      }
    },

    // ── UI helpers ──────────────────────────────────────────────────────────
    showHoverCard(card, event) {
      clearTimeout(this.hoverTimer);
      this.hoverTimer = setTimeout(() => {
        if (!card?.image_uri) return;
        const tooltipWidth = 192; // w-48
        const margin = 16;
        let x = event.clientX + margin;
        if (x + tooltipWidth > window.innerWidth) {
          x = event.clientX - tooltipWidth - margin;
        }
        const y = Math.max(8, Math.min(event.clientY - 60, window.innerHeight - 280));
        this.hoverStyle = `left:${x}px;top:${y}px`;
        this.hoverCard = card;
      }, 150);
    },

    hideHoverCard() {
      clearTimeout(this.hoverTimer);
      this.hoverCard = null;
    },

    // ── Card preview extras ────────────────────────────────────────────────
    async fetchRulings() {
      if (!this.selectedCard?.id) return;
      this.cardRulingsLoading = true;
      try {
        const r = await fetch(`/api/cards/rulings?id=${encodeURIComponent(this.selectedCard.id)}`);
        const data = await r.json();
        this.cardRulings = data.rulings ?? [];
      } finally {
        this.cardRulingsLoading = false;
      }
    },

    async fetchSimilarCards(id) {
      this.similarCards = [];
      this.similarCardsLoading = true;
      try {
        const r = await fetch(`/api/cards/similar?id=${encodeURIComponent(id)}`);
        const data = await r.json();
        this.similarCards = data.cards ?? [];
      } finally {
        this.similarCardsLoading = false;
      }
    },

    legalityClass(status) {
      return {
        legal:      "bg-green-900/50 text-green-400 border border-green-900",
        banned:     "bg-red-900/50 text-red-400 border border-red-900",
        restricted: "bg-amber-900/50 text-amber-400 border border-amber-900",
      }[status] ?? "bg-gray-800/50 text-gray-600 border border-gray-800";
    },

    // ── Share ──────────────────────────────────────────────────────────────
    async shareDeck() {
      if (!this.currentDeck?.id) return;
      this.shareLoading = true;
      this.shareUrl = "";
      this.shareCopied = false;
      this.showShareModal = true;
      try {
        await this.saveDeck();
        const r = await fetch(`/api/decks/${this.currentDeck.id}/share`, { method: "POST" });
        if (!r.ok) throw new Error();
        const data = await r.json();
        this.shareUrl = `${window.location.origin}/share/${data.token}`;
      } finally {
        this.shareLoading = false;
      }
    },

    async copyShareUrl() {
      if (!this.shareUrl) return;
      await navigator.clipboard.writeText(this.shareUrl);
      this.shareCopied = true;
      setTimeout(() => (this.shareCopied = false), 2000);
    },

    // ── Deck statistics ────────────────────────────────────────────────────
    parseMC(manaCost) {
      if (!manaCost) return 0;
      const symbols = manaCost.match(/\{([^}]+)\}/g) || [];
      let cmc = 0;
      for (const sym of symbols) {
        const inner = sym.slice(1, -1);
        if (/^\d+$/.test(inner)) cmc += parseInt(inner);
        else if (inner !== "X") cmc += 1; // colored, snow, hybrid pips each = 1; X = 0
      }
      return cmc;
    },

    get deckStats() {
      if (!this.currentDeck?.cards?.length) return null;
      const nonCmd = this.currentDeck.cards.filter((c) => !c.is_commander);
      const nonLand = nonCmd.filter((c) => this.getCardType(c.type_line) !== "Land");

      // Mana curve — CMC 0 through 7+
      const curve = Array(8).fill(0);
      let totalCMC = 0, cmcCards = 0;
      for (const card of nonLand) {
        const cmc = this.parseMC(card.mana_cost);
        curve[Math.min(cmc, 7)] += card.quantity;
        totalCMC += cmc * card.quantity;
        cmcCards += card.quantity;
      }
      const avgCMC = cmcCards > 0 ? totalCMC / cmcCards : 0;
      const maxCurve = Math.max(...curve, 1);

      // Color pips across all non-commander cards
      const pips = { W: 0, U: 0, B: 0, R: 0, G: 0 };
      for (const card of nonCmd) {
        if (!card.mana_cost) continue;
        const symbols = card.mana_cost.match(/\{([^}]+)\}/g) || [];
        for (const sym of symbols) {
          const inner = sym.slice(1, -1);
          if (Object.prototype.hasOwnProperty.call(pips, inner)) pips[inner] += card.quantity;
        }
      }
      const maxPips = Math.max(...Object.values(pips), 1);
      const pipEntries = Object.entries(pips)
        .filter(([, v]) => v > 0)
        .map(([color, count]) => ({ color, count }));

      // Card type counts (reuse cardsByType which excludes commander)
      const typeOrder = ["Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Land", "Other"];
      const typeData = typeOrder
        .map((type) => ({
          type,
          count: (this.cardsByType[type] || []).reduce((s, c) => s + c.quantity, 0),
        }))
        .filter((t) => t.count > 0);
      const maxType = Math.max(...typeData.map((t) => t.count), 1);

      return { curve, avgCMC, maxCurve, pips, maxPips, pipEntries, typeData, maxType };
    },

    colorClass(color) {
      return {
        W: "bg-yellow-100 text-yellow-900 border border-yellow-300",
        U: "bg-blue-500 text-white",
        B: "bg-gray-900 text-white border border-gray-500",
        R: "bg-red-500 text-white",
        G: "bg-green-600 text-white",
      }[color] ?? "bg-gray-500 text-white";
    },
  }));
});
