import pytest
from src.ingest import clean_single_note, is_valid_note_item, clean_note_items
from src.advisor import FragranceAdvisor, STOPWORDS_NOTES, CANONICAL_NOTES


@pytest.fixture
def advisor_mock():
    """Crea un'istanza leggera di FragranceAdvisor senza caricare ChromaDB."""
    adv = FragranceAdvisor.__new__(FragranceAdvisor)
    adv.catalog_notes = {"cannella", "vaniglia", "bergamotto", "lime", "pepe rosa"}
    adv.catalog_products = []
    return adv


# ==============================================================================
# 1. TEST PULIZIA E SANITIZZAZIONE DELLE NOTE (ingest.py)
# ==============================================================================
def test_clean_single_note_removes_prefixes():
    assert clean_single_note("Si aprono con un esplosione esperidata di lime") == "Lime"
    assert clean_single_note("Alla mimosa") == "Mimosa"
    assert clean_single_note("Accordo di Ambra Grigia") == "Ambra Grigia"
    assert clean_single_note("Un tocco di pepe rosa") == "Pepe rosa"


def test_is_valid_note_item_filters_narrative_and_marketing():
    # Note legittime
    assert is_valid_note_item("Bergamotto") is True
    assert is_valid_note_item("Vaniglia del Madagascar") is True
    assert is_valid_note_item("Fiori d'Arancio") is True

    # Frasi e verbi da scartare
    assert is_valid_note_item("Intensamente rinfrescanti") is False
    assert is_valid_note_item("La rotondità del musk si unisce ai toni legnosi") is False
    assert is_valid_note_item("Sensuale ed elegante") is False
    assert is_valid_note_item("Questa fragranza avvolge la pelle con dolcezza infinita") is False


def test_clean_note_items_pipeline():
    raw = "Si aprono con un esplosione di lime, Bergamotto, Intensamente rinfrescanti, 100 ml, EDP"
    cleaned = clean_note_items(raw)
    assert "Lime" in cleaned
    assert "Bergamotto" in cleaned
    assert "Intensamente rinfrescanti" not in cleaned
    assert "100 ml" not in cleaned
    assert "EDP" not in cleaned


# ==============================================================================
# 2. TEST ESTRAZIONE DELLE NOTE E FILTRO STOPWORD (advisor.py)
# ==============================================================================
def test_extract_target_notes_excludes_stopwords(advisor_mock):
    # La preposizione 'alla' non deve essere scambiata per una nota olfattiva
    query = "vorrei un profumo invernale alla cannella"
    notes = advisor_mock._extract_target_notes(query)
    assert "cannella" in notes
    assert "alla" not in notes
    assert "invernale" not in notes


# ==============================================================================
# 3. TEST RICONOSCIMENTO DI GENERE (advisor.py)
# ==============================================================================
def test_detect_gender(advisor_mock):
    # Riconoscimento maschile puro
    assert advisor_mock._detect_gender("Aventus", ["uomo", "per lui"]) == "Per Lui"
    
    # Nessun falso positivo su parole come 'soleil'
    assert advisor_mock._detect_gender("Soleil de Capri", ["soleil", "uomo"]) == "Per Lui"

    # Prodotti con tag sia maschili che femminili devono risultare Unisex
    assert advisor_mock._detect_gender("Megamare", ["uomo", "donna"]) == "Unisex"

    # Priorità del nome proprio
    assert advisor_mock._detect_gender("Silver Man", ["donna"]) == "Per Lui"
    assert advisor_mock._detect_gender("Interlude Woman", ["uomo"]) == "Per Lei"


# ==============================================================================
# 4. TEST RICONOSCIMENTO STAGIONE (advisor.py)
# ==============================================================================
def test_detect_season(advisor_mock):
    assert advisor_mock._detect_season("Acquatica, Agrumata", []) == "Primavera / Estate"
    assert advisor_mock._detect_season("Cuoiata, Tabaccosa", []) == "Autunno / Inverno"
    assert advisor_mock._detect_season("", ["profumi invernali"]) == "Autunno / Inverno"
    assert advisor_mock._detect_season("", ["profumi estivi", "profumi invernali"]) == "Quattro Stagioni"


# ==============================================================================
# 5. TEST PARSER PREZZI E BUDGET (advisor.py)
# ==============================================================================
def test_extract_price_constraints(advisor_mock):
    min_p, max_p, q = advisor_mock._extract_price_constraints("cerco un profumo sotto i 150€", None)
    assert min_p is None
    assert max_p == 150.0
    assert "150" not in q

    min_p, max_p, q = advisor_mock._extract_price_constraints("vorrei spendere tra 80 e 120 euro", None)
    assert min_p == 80.0
    assert max_p == 120.0

    # Test prezzo relativo rispetto al profumo attivo
    active = {"price": 100.0, "name": "Profumo X"}
    min_p, max_p, _ = advisor_mock._extract_price_constraints("ne vorrei uno più economico", active)
    assert max_p == 99.5

# ==============================================================================
# 6. TEST KEYWORD BOOST & RICERCA IBRIDA (advisor.py)
# ==============================================================================
def test_find_keyword_matches_prioritizes_exact_notes(advisor_mock):
    advisor_mock.catalog_products = [
        {
            "name": "Profumo Speziato Invernale",
            "price": 110.0,
            "family": "Speziata",
            "tags": ["inverno", "uomo"],
            "olfactory_pyramid": {"top": ["Cannella", "Pepe"], "heart": [], "base": []},
            "description": "Una fragranza calda e speziata."
        },
        {
            "name": "Profumo Estivo Agrumato",
            "price": 90.0,
            "family": "Agrumata",
            "tags": ["estate", "unisex"],
            "olfactory_pyramid": {"top": ["Bergamotto", "Lime"], "heart": [], "base": []},
            "description": "Fresco e marino."
        },
        {
            "name": "Profumo Speziato Fuori Budget",
            "price": 250.0,
            "family": "Speziata",
            "tags": ["inverno"],
            "olfactory_pyramid": {"top": ["Cannella"], "heart": [], "base": []},
            "description": "Creazione di lusso con cannella pura."
        }
    ]

    # Ricerca con nota specifica e tetto di budget a 150€
    matches = advisor_mock._find_keyword_matches(
        target_notes=["cannella"],
        min_price=None,
        max_price=150.0,
        query="vorrei un profumo invernale alla cannella",
        limit=3
    )

    # Deve trovare solo il profumo compatibile con la nota e sotto il budget
    assert len(matches) == 1
    assert matches[0]["name"] == "Profumo Speziato Invernale"
    
# ==============================================================================
# 7. TEST ROUTER INTENTI: VALUTA vs CAMBIA (advisor.py)
# ==============================================================================
def test_determine_intent_stay_vs_switch(advisor_mock):
    active_perfume = {"name": "Aventus", "price": 250.0}

    # Casi che DEVONO restare sul profumo attivo (VALUTA)
    assert advisor_mock._determine_intent("quali sono le note di cuore?", active_perfume) == "VALUTA"
    assert advisor_mock._determine_intent("quanto dura sulla pelle?", active_perfume) == "VALUTA"
    assert advisor_mock._determine_intent("è adatto per l'ufficio?", active_perfume) == "VALUTA"
    assert advisor_mock._determine_intent("quanto costa?", active_perfume) == "VALUTA"

    # Casi che DEVONO cercare un profumo diverso (CAMBIA)
    assert advisor_mock._determine_intent("vorrei qualcosa di più economico", active_perfume) == "CAMBIA"
    assert advisor_mock._determine_intent("mostrami un'alternativa", active_perfume) == "CAMBIA"
    assert advisor_mock._determine_intent("cambiamo profumo", active_perfume) == "CAMBIA"
    assert advisor_mock._determine_intent("cerco un altro profumo fresco", active_perfume) == "CAMBIA"


# ==============================================================================
# 8. TEST MACCHINA A STATI PERCORSO GUIDATO (advisor.py)
# ==============================================================================
def test_guided_flow_state_transitions(advisor_mock):
    from collections import defaultdict
    advisor_mock.guided_states = defaultdict(lambda: {"step": None, "answers": []})
    advisor_mock.active_perfumes = {}
    advisor_mock.sessions = defaultdict(list)

    session_id = "test_user_123"

    # Avvio del percorso guidato
    res1 = advisor_mock.advise("guidami", session_id=session_id)
    assert res1["step"] == 1
    assert res1["mode"] == "guided"

    # Risposta Step 1 (Famiglia)
    res2 = advisor_mock.advise("🍋 Fresco o Agrumato", session_id=session_id)
    assert res2["step"] == 2
    assert advisor_mock.guided_states[session_id]["answers"] == ["🍋 Fresco o Agrumato"]

    # Risposta Step 2 (Destinatario)
    res3 = advisor_mock.advise("Per Lui", session_id=session_id)
    assert res3["step"] == 3
    assert advisor_mock.guided_states[session_id]["answers"] == ["🍋 Fresco o Agrumato", "Per Lui"]

    # Risposta Step 3 (Occasione)
    res4 = advisor_mock.advise("Primavera / Estate", session_id=session_id)
    assert res4["step"] == 4
    assert advisor_mock.guided_states[session_id]["answers"] == ["🍋 Fresco o Agrumato", "Per Lui", "Primavera / Estate"]