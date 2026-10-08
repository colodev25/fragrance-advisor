"""Recommendation admission, ranking and conversational continuity without network calls."""
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from src.advisor import FragranceAdvisor
from src.recommendation_preferences import (PreferenceMatcher, note_matches, price_constraints,
    recommendation_request, recipient_evidence, season_evidence)
from src.session_store import SessionStore
from src.search import FragranceSearchEngine


def product(identifier="p1", name="Creazione A", price=90, family="Agrumata", notes=None, tags=None, **extra):
    notes = ["Iris", "Vaniglia"] if notes is None else notes
    return {"id": identifier, "name": name, "price": price, "brand": "Brand", "family": family,
            "in_stock": True, "ptype": "EDP", "tags": ["unisex", "estate", "ufficio"] if tags is None else tags,
            "olfactory_pyramid": {"top": notes, "heart": [], "base": []}, "unpositioned_notes": [],
            "description": "", "usage_profile": "", "semantic_text": "Note: " + ", ".join(notes),
            "urls": {"product_page": "https://shop.test/product", "add_to_cart": "https://shop.test/cart/1:1"}, **extra}


def advisor_for(tmp_path, catalog):
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.catalog_products = catalog
    advisor.catalog_notes = set()
    advisor.sessions = defaultdict(list)
    advisor.active_perfumes = {}
    advisor.guided_states = defaultdict(lambda: {"step": None, "answers": []})
    advisor.session_store = SessionStore(str(tmp_path / "preferences.db"))
    advisor.search_engine = MagicMock()
    advisor.search_engine.search.return_value = {"ids": [[p["id"] for p in catalog]]}
    def response(**kwargs):
        return "Presentazione verificata" if "response_validator" not in kwargs else '{"selection":"PRODOTTO_1","reply":"Scelta dal catalogo"}'
    advisor._chat_completion = MagicMock(side_effect=response)
    return advisor


@pytest.mark.parametrize("query,expected_positive,expected_negative", [
    ("senza rosa", [], ["rosa"]),
    ("non voglio rosa", [], ["rosa"]),
    ("non voglio un profumo con rosa", [], ["rosa"]),
    ("evita rosa, vaniglia e oud", [], ["rosa", "vaniglia", "oud"]),
    ("con vaniglia ma senza rosa", ["vaniglia"], ["rosa"]),
    ("senza rosa e con vaniglia", ["vaniglia"], ["rosa"]),
    ("non solo rosa ma anche iris", ["rosa", "iris"], []),
    ("senza pepe rosa", [], ["pepe rosa"]),
    ("senza rosa ma con pepe rosa", ["pepe rosa"], ["rosa"]),
])
def test_note_polarity(query, expected_positive, expected_negative):
    positive, negative = PreferenceMatcher([]).note_mentions(query)
    assert [note for note, *_ in positive] == expected_positive
    assert [note for note, *_ in negative] == expected_negative


@pytest.mark.parametrize("query,minimum,maximum", [
    ("sotto 120€", None, 119.99), ("massimo 120 euro", None, 120),
    ("oltre 200€", 200.01, None), ("almeno 200€", 200, None),
    ("tra 80 e 120 euro", 80, 120), ("120€ - 200€", 120, 200),
    ("budget di 99,50€", None, 99.50), ("<= 100", None, 100),
    ("<100", None, 99.99), (">=100", 100, None), (">100", 100.01, None),
    ("massimo 0€", None, 0), ("profumo 100 ml", None, None),
    ("non più di 100€", None, 100), ("non voglio spendere più di 100 euro", None, 100),
])
def test_price_boundaries(query, minimum, maximum):
    assert price_constraints(query)[:2] == (minimum, maximum)


def test_multiple_required_notes_and_or_groups():
    matcher = PreferenceMatcher([product(notes=["Iris"]), product("p2", notes=["Iris", "Vaniglia"])])
    both = matcher.update("con iris e vaniglia")
    assert [p["id"] for p in matcher.select(both)[0]] == ["p2"]
    either = matcher.update("con iris o vaniglia")
    assert len(matcher.select(either)[0]) == 2


def test_rose_and_pink_pepper_are_distinct():
    assert not note_matches("rosa", "Pepe rosa")
    assert not note_matches("rosa", "Brazilian pink pepper")
    assert note_matches("rosa", "Rosa e pepe rosa")
    assert note_matches("rosa", "Rosa damascena")
    matcher = PreferenceMatcher([product(notes=["Pepe rosa"])])
    assert len(matcher.select(matcher.update("senza rosa"))[0]) == 1
    assert matcher.select(matcher.update("senza pepe rosa"))[0] == []


def test_exclusions_use_unpositioned_notes_and_incomplete_records_are_rejected():
    catalog = [product(notes=[], unpositioned_notes=["Rosa"]), product("p2", notes=[]),
               product("p3", notes=["Iris"])]
    matcher = PreferenceMatcher(catalog)
    assert [p["id"] for p in matcher.select(matcher.update("senza rosa"))[0]] == ["p3"]


def test_description_mentions_are_evidence_but_names_are_not():
    matcher = PreferenceMatcher([product(notes=[], description="Note di iris e vaniglia."),
                                 product("p2", name="Vaniglia", notes=[])])
    assert [p["id"] for p in matcher.select(matcher.update("con vaniglia"))[0]] == ["p1"]


def test_negated_description_does_not_declare_the_note():
    matcher = PreferenceMatcher([product(notes=["Iris"], description="Senza rosa, con iris.")])
    assert matcher.select(matcher.update("con rosa"))[0] == []


def test_full_matches_are_not_padded_with_relaxed_cards():
    matcher = PreferenceMatcher([product(), product("p2", family="Cuoiata", tags=["uomo", "inverno"])])
    prefs = matcher.update("agrumato per lei in estate")
    selected, differences = matcher.select(prefs, limit=3)
    assert [p["id"] for p in selected] == ["p1"]
    assert differences == {"p1": []}


def test_relaxation_is_available_only_for_preferences():
    matcher = PreferenceMatcher([product(family="Cuoiata", tags=["uomo", "inverno"])])
    selected, differences = matcher.select(matcher.update("agrumato per lei in estate"))
    assert selected and len(differences["p1"]) == 3
    assert matcher.select(matcher.update("solo agrumato per lei in estate"))[0] == []
    assert matcher.select(matcher.update("massimo 50€"))[0] == []
    assert matcher.select(matcher.update("senza vaniglia"))[0] == []


def test_unknown_and_inferred_fields_do_not_count_as_confirmed_matches():
    assert recipient_evidence("Creazione", []) is None
    assert season_evidence("", [], description="Caldo, avvolgente e versatile.") == (None, "unknown")
    matcher = PreferenceMatcher([product(tags=[], family="Agrumata")])
    selected, differences = matcher.select(matcher.update("per lei in estate"))
    assert selected and "stagionalità dedotta dalla famiglia" in differences["p1"]
    assert matcher.select(matcher.update("solo per lei in estate"))[0] == []


def test_known_unisex_products_are_compatible_with_male_and_female_preferences():
    matcher = PreferenceMatcher([product()])
    for recipient in ("Per Lui", "Per Lei", "Unisex"):
        assert matcher.select(matcher.update(recipient))[1] == {"p1": []}


def test_explicit_season_outweighs_family_inference():
    assert season_evidence("Agrumata", ["profumi invernali"]) == ("winter", "declared")
    assert season_evidence("", ["estate", "inverno"]) == ("all", "declared")


def test_budget_update_and_removal_preserve_other_preferences():
    matcher = PreferenceMatcher([])
    original = matcher.update("con iris senza rosa massimo 150€")
    cheaper = matcher.update("qualcosa di più economico", original, {"price": 100})
    assert cheaper["max_price"] == 99.99
    assert cheaper["excluded_notes"] == ["rosa"] and cheaper["required_notes"] == [["iris"]]
    raised = matcher.update("budget di 200€", original)
    assert raised["max_price"] == 200
    free = matcher.update("nessun limite di budget", raised)
    assert "max_price" not in free
    assert matcher.bounds(free, 80) == (None, 80)
    assert original["max_price"] == 150


def test_explicit_note_change_replaces_required_notes_and_can_remove_exclusion():
    matcher = PreferenceMatcher([])
    prefs = matcher.update("con iris senza rosa")
    updated = matcher.update("ora con rosa", prefs)
    assert updated["required_notes"] == [["rosa"]] and updated["excluded_notes"] == []
    assert matcher.update("nessuna esclusione", prefs)["excluded_notes"] == []


@pytest.mark.parametrize("query,expected", [
    ("È senza rosa?", False), ("Quanto costa?", False), ("Vorrei sapere le note", False),
    ("Non voglio rosa", True), ("Una alternativa a Creazione A sotto 100€", True),
    ("È senza rosa? Cercami un'alternativa", True),
])
def test_information_and_recommendation_routing(query, expected):
    assert recommendation_request(query) is expected


def test_guided_uses_api_cap_and_does_not_pad_partial_matches(tmp_path):
    advisor = advisor_for(tmp_path, [product(), product("p2", price=110), product("p3", family="Legnosa")])
    result = advisor._generate_guided_recommendations(["🍋 Fresco o Agrumato", "Per Lei", "Primavera / Estate", "Nessun limite di budget"], "customer", 100)
    assert [p["name"] for p in result["products"]] == ["Creazione A"]
    assert len(result["products"]) == 1
    assert "alternativa" not in result["reply"]
    assert advisor.search_engine.search.call_args.kwargs["max_price"] == 100


def test_guided_alternative_contains_deterministic_notice(tmp_path):
    advisor = advisor_for(tmp_path, [product(family="Cuoiata", tags=["unisex", "inverno"])])
    result = advisor._generate_guided_recommendations(["Fresco o Agrumato", "Unisex", "Primavera / Estate", "sotto 120€"], "customer")
    assert len(result["products"]) == 1
    assert "è un'alternativa" in result["reply"] and "famiglia olfattiva diversa" in result["reply"]


def test_hard_empty_results_never_call_embedding_or_llm(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    result = advisor.advise("cerco un profumo senza vaniglia", "customer")
    assert result["products"] == []
    advisor.search_engine.search.assert_not_called()
    advisor._chat_completion.assert_not_called()


def test_inconsistent_bounds_preserve_previous_preferences_and_skip_llm(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    advisor.advise("con iris massimo 100€", "customer")
    before = advisor.session_store.get_session("customer")["guided_state"]["preferences"]
    calls = advisor._chat_completion.call_count
    result = advisor.advise("cerco un profumo tra 120 e 200 euro", "customer", max_price=100)
    assert "si contraddicono" in result["reply"] and result["products"] == []
    assert advisor._chat_completion.call_count == calls
    assert advisor.session_store.get_session("customer")["guided_state"]["preferences"] == before


def test_persisted_preferences_survive_navigation_and_follow_up(tmp_path):
    catalog = [product(price=90), product("p2", name="Creazione B", price=70), product("p3", price=50, notes=["Iris", "Rosa"])]
    advisor = advisor_for(tmp_path, catalog)
    first = advisor.advise("con iris senza rosa massimo 100€ per lei in estate", "customer", max_price=95)
    assert first["products"][0]["price"] == 90
    # A fresh advisor sees the same stored preference profile, with no prior RAM state.
    restarted = advisor_for(tmp_path, catalog)
    second = restarted.advise("vorrei qualcosa di più economico", "customer", session_context=first["session_context"])
    assert second["products"][0]["price"] == 70
    prefs = restarted.session_store.get_session("customer")["guided_state"]["preferences"]
    assert prefs["excluded_notes"] == ["rosa"] and prefs["season"] == "summer" and prefs["recipient"] == "female"
    assert restarted.search_engine.search.call_args.kwargs["max_price"] == 89.99


def test_guided_restart_clears_preferences(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    advisor.advise("senza rosa massimo 100€", "customer")
    advisor.advise("ricomincia percorso guidato", "customer")
    assert advisor.session_store.get_session("customer")["guided_state"]["preferences"] == {}


def test_named_recommendation_obeys_cap_while_information_can_show_price(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    refused = advisor.advise("Vorrei Creazione A sotto 50€", "customer")
    assert refused["products"] == []
    advisor._chat_completion.assert_not_called()
    info = advisor.advise("Quanto costa Creazione A?", "customer")
    assert info["products"][0]["price"] == 90


def test_named_reference_search_does_not_return_the_reference_product(tmp_path):
    advisor = advisor_for(tmp_path, [product(price=120), product("p2", name="Creazione B", price=90)])
    result = advisor.advise("Una alternativa a Creazione A sotto 100€", "customer")
    assert result["products"][0]["name"] == "Creazione B"


def test_candidates_outside_semantic_shortlist_can_still_be_found(tmp_path):
    advisor = advisor_for(tmp_path, [product(notes=["Rosa"]), product("p2", notes=["Iris"])])
    advisor.search_engine.search.return_value = {"ids": [["p1"]]}
    result = advisor.advise("con iris senza rosa", "customer")
    assert result["products"][0]["name"] == "Creazione A"
    assert advisor.active_perfumes == {}
    assert advisor.session_store.get_session("customer")["active_perfume"]["id"] == "p2"


def test_equal_names_use_stable_catalog_id_for_card_data(tmp_path):
    advisor = advisor_for(tmp_path, [product(notes=["Rosa"]), product("p2", notes=["Iris"])])
    card = advisor._enrich_product_payload(advisor._product_data(advisor.catalog_products[1]))
    assert card["key_notes"] == ["Iris"]


def test_search_can_retrieve_more_than_ten_candidates():
    engine = FragranceSearchEngine.__new__(FragranceSearchEngine)
    engine.collection = MagicMock()
    engine.collection.count.return_value = 80
    engine.collection.query.return_value = {"ids": [[]]}
    engine.search("iris", n_results=40)
    assert engine.collection.query.call_args.kwargs["n_results"] == 40


def test_unknown_exclusions_ask_for_clarification_without_model_calls(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    for query in ("senza unicorno", "senza alcool", "senza rosa e unicorno"):
        response = advisor.advise(query, "customer")
        assert "Riformula" in response["reply"] and response["products"] == []
    advisor._chat_completion.assert_not_called()


@pytest.mark.parametrize("query", ["con unicorno", "con iris e unicorno", "alla mozzarella"])
def test_unknown_required_notes_are_not_silently_dropped(tmp_path, query):
    advisor = advisor_for(tmp_path, [product()])
    result = advisor.advise(query, "customer")
    assert "Riformula" in result["reply"] and result["products"] == []
    advisor._chat_completion.assert_not_called()


def test_semantic_query_does_not_promote_excluded_notes(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    advisor.advise("con iris senza rosa massimo 100€", "customer")
    query = advisor.search_engine.search.call_args.kwargs["query"]
    assert "rosa" not in query and "iris" in query and "100" not in query


def test_negative_family_is_never_relaxed():
    matcher = PreferenceMatcher([product(family="Floreale"), product("p2", family="Legnosa")])
    assert [p["id"] for p in matcher.select(matcher.update("non voglio un profumo floreale"))[0]] == ["p2"]


def test_inferred_family_is_reported_as_inferred():
    matcher = PreferenceMatcher([product(family="", family_inference={"value": "Agrumata"})])
    assert matcher.select(matcher.update("agrumato"))[1] == {"p1": ["famiglia dedotta, non dichiarata"]}


def test_family_terms_are_preferences_even_if_legacy_notes_contain_them():
    matcher = PreferenceMatcher([product(notes=["Agrumata", "Iris"])])
    prefs = matcher.update("agrumata")
    assert not prefs.get("required_notes") and prefs["families"] == ["agrumata"]


def test_non_solo_does_not_create_strict_family_rule():
    prefs = PreferenceMatcher([]).update("non solo agrumato")
    assert prefs["strict"] == []


def test_common_english_note_names_use_the_same_exclusion_and_requirement():
    matcher = PreferenceMatcher([product(notes=["Rose", "Vanilla"]), product("p2", notes=["Pink pepper", "Vanilla"])])
    assert [p["id"] for p in matcher.select(matcher.update("con vaniglia senza rosa"))[0]] == ["p2"]
    assert not note_matches("rose", "Pink pepper")


def test_guided_budget_clarification_retains_other_answers(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    advisor.advise("guidami", "customer", max_price=100)
    for answer in ["agrumato senza rosa", "per lei", "estate", "oltre 200€"]:
        result = advisor.advise(answer, "customer")
    assert "si contraddicono" in result["reply"]
    response = advisor.advise("massimo 95€", "customer")
    assert len(response["products"]) == 1
    prefs = advisor.session_store.get_session("customer")["guided_state"]["preferences"]
    assert prefs["families"] == ["agrumata"] and prefs["excluded_notes"] == ["rosa"] and prefs["season"] == "summer"


def test_unresolved_guided_note_constraint_is_not_lost_between_answers(tmp_path):
    advisor = advisor_for(tmp_path, [product()])
    advisor.advise("guidami", "customer")
    for answer in ["agrumato senza unicorno", "unisex", "estate", "nessun limite di budget"]:
        result = advisor.advise(answer, "customer")
    assert "Riformula" in result["reply"] and result["products"] == []
    advisor._chat_completion.assert_not_called()
    resolved = advisor.advise("senza rosa", "customer")
    assert len(resolved["products"]) == 1


def test_excluding_one_or_option_retains_the_remaining_requirement():
    matcher = PreferenceMatcher([])
    original = matcher.update("con iris o vaniglia")
    assert matcher.update("senza vaniglia", original)["required_notes"] == [["iris"]]


def test_negative_family_replaces_an_earlier_conflicting_requirement():
    matcher = PreferenceMatcher([product(), product("p2", family="Floreale")])
    original = matcher.update("solo floreale")
    updated = matcher.update("non voglio floreale", original)
    assert not updated.get("families") and updated["strict"] == []
    assert [p["id"] for p in matcher.select(updated)[0]] == ["p1"]


@pytest.mark.parametrize("query", ["Non mi piace questo profumo", "Non mi piace Creazione A"])
def test_rejecting_a_product_searches_for_a_different_one(tmp_path, query):
    advisor = advisor_for(tmp_path, [product(), product("p2", name="Creazione B")])
    advisor.advise("con iris", "customer")
    assert advisor.advise(query, "customer")["products"][0]["name"] == "Creazione B"


def test_sweet_style_is_a_family_preference_and_can_be_excluded():
    matcher = PreferenceMatcher([product(family="Gourmand"), product("p2", family="Agrumata")])
    assert [p["id"] for p in matcher.select(matcher.update("cerco un profumo dolce"))[0]] == ["p1"]
    assert [p["id"] for p in matcher.select(matcher.update("niente di dolce"))[0]] == ["p2"]


@pytest.mark.parametrize("query", ["con note dolci", "con note fresche"])
def test_style_words_are_preferences_instead_of_unknown_notes(query):
    prefs = PreferenceMatcher([]).update(query)
    assert prefs["families"] and not prefs.get("unrecognized_required_notes")
