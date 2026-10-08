"""Catalog-backed card details, without constructing a model or search client."""
import pytest

from src.advisor import FragranceAdvisor


def card(pyramid=None, unpositioned=None, family="Agrumata", card_type="slideover", ptype="EDP", tags=None):
    product = {"id": "p1", "name": "Esempio", "brand": "Brand", "price": 90,
               "family": family, "ptype": ptype, "tags": tags or [], "description": "",
               "olfactory_pyramid": pyramid or {"top": [], "heart": [], "base": []},
               "unpositioned_notes": unpositioned or [], "urls": {}}
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.catalog_products = [product]
    return advisor._enrich_product_payload(advisor._product_data(product), card_type=card_type)


@pytest.mark.parametrize("card_type", ["standard", "slideover"])
def test_full_pyramid_and_additional_notes_are_separate(card_type):
    pyramid = {"top": ["Bergamotto", "Limone", "Mandarino"], "heart": ["Iris"], "base": ["Sandalo"]}
    result = card(pyramid, ["Cacao", "Sale"], card_type=card_type)
    assert result["olfactory_pyramid"] == pyramid
    assert result["unpositioned_notes"] == ["Cacao", "Sale"]
    assert result["card_type"] == card_type
    assert "Sale" in result["key_notes"]


def test_duplicate_notes_are_cleaned_without_guessing_positions():
    result = card({"top": [" Iris ", "IRIS", "Thé"], "heart": [], "base": ["Sandalo"]},
                  ["iris", "the", " Sale ", "SALE", "", "  ", 12])
    assert result["olfactory_pyramid"] == {"top": ["Iris", "Thé"], "heart": [], "base": ["Sandalo"]}
    assert result["unpositioned_notes"] == ["Sale"]


def test_same_note_can_remain_in_two_declared_stages():
    result = card({"top": ["Iris"], "heart": ["Iris"], "base": []}, ["IRIS"])
    assert result["olfactory_pyramid"]["top"] == ["Iris"]
    assert result["olfactory_pyramid"]["heart"] == ["Iris"]
    assert result["unpositioned_notes"] == []
    assert result["key_notes"] == ["Iris"]


def test_only_unpositioned_notes_populate_the_brief_summary():
    result = card(unpositioned=["Iris", "Vaniglia", "Sale"])
    assert result["key_notes"] == ["Iris", "Vaniglia", "Sale"]
    assert not any(result["olfactory_pyramid"].values())


def test_family_is_not_substituted_for_missing_notes():
    result = card(family="Agrumata, Verde")
    assert result["key_notes"] == result["unpositioned_notes"] == []
    assert not any(result["olfactory_pyramid"].values())


def test_summary_is_bounded_but_details_keep_all_catalog_notes():
    pyramid = {"top": ["A", "B", "C"], "heart": ["D", "E", "F"], "base": ["G", "H", "I"]}
    result = card(pyramid, ["J", "K"])
    assert len(result["key_notes"]) == 6
    assert result["olfactory_pyramid"] == pyramid
    assert result["unpositioned_notes"] == ["J", "K"]


def test_missing_catalog_record_has_empty_note_fields():
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.catalog_products = []
    result = advisor._enrich_product_payload({"id": "missing", "name": "Esempio",
        "family": "Legnosa", "document": "Note di testa: Iris"})
    assert result["key_notes"] == result["unpositioned_notes"] == []
    assert not any(result["olfactory_pyramid"].values())


def test_legacy_catalog_without_new_fields_remains_compatible():
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    product = {"id": "legacy", "name": "Esempio", "brand": "Brand", "price": 90,
               "olfactory_pyramid": {"top": ["Iris"]}}
    advisor.catalog_products = [product]
    result = advisor._enrich_product_payload(advisor._product_data(product))
    assert result["olfactory_pyramid"] == {"top": ["Iris"], "heart": [], "base": []}
    assert result["unpositioned_notes"] == []


@pytest.mark.parametrize("value,name,expected", [
    ("Eau de parfum, unisex", "Esempio", "Eau de Parfum"),
    ("Eau de Parfum Unisex", "Esempio", "Eau de Parfum"),
    ("EDP; per lei", "Esempio", "Eau de Parfum"),
    ("Extrait de parfum, unisex", "Esempio", "Extrait de Parfum"),
    ("Eau de Toilette • maschile", "Esempio", "Eau de Toilette"),
    ("Eau de Cologne, per lui", "Esempio", "Eau de Cologne"),
    ("Olio profumato, unisex", "Esempio", "Olio profumato"),
    ("Profumo artistico, unisex", "Esempio EDP", "Eau de Parfum"),
    ("", "Esempio", "Profumo Artistico"),
])
def test_display_type_keeps_only_the_first_characteristic(value, name, expected):
    assert FragranceAdvisor._display_perfume_type(value, name) == expected


@pytest.mark.parametrize("card_type", ["standard", "slideover"])
def test_display_profile_has_one_recipient_and_a_plain_season(card_type):
    result = card(ptype="Eau de parfum, unisex", card_type=card_type)
    assert result["ptype"] == "Eau de Parfum"
    assert result["traits"] == "Eau de Parfum • Unisex • Primavera / Estate"
    assert result["traits"].casefold().count("unisex") == 1


def test_internal_season_evidence_remains_distinct():
    from src.recommendation_preferences import season_evidence
    assert season_evidence("Agrumata", []) == ("summer", "inferred")
    assert season_evidence("Agrumata", ["estate"]) == ("summer", "declared")


def test_missing_catalog_record_also_has_a_clean_type_and_season():
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.catalog_products = []
    result = advisor._enrich_product_payload({"id": "missing", "name": "Esempio",
        "ptype": "Extrait de parfum, unisex", "family": "Ambrata"})
    assert result["ptype"] == "Extrait de Parfum"
    assert result["traits"] == "Extrait de Parfum • Unisex • Autunno / Inverno"
