"""Product names are resolved before retrieval/model work, without external services."""
import json
from pathlib import Path

import pytest

from src.product_identity import ProductIdentity, name_text
from tests.session_client import client_advise
from tests.test_recommendation_preferences import advisor_for, product


def perfumes():
    return [
        product('orange_extrait', name='Orange Crush Extrait de Parfum', brand='Fugazzi', ptype='Extrait de Parfum'),
        product('orange_edp', name='Orange Crush Eau de Parfum', brand='Fugazzi'),
        product('angel_edp', name='Angel Dust Eau de Parfum', brand='Fugazzi'),
        product('angel_extrait', name='Angel Dust Extrait de Parfum', brand='Fugazzi', ptype='Extrait de Parfum'),
        product('signature', name='Signature EDP 100 ml', brand='Brand'),
        product('costa', name='Signature Costa Azzurra EDP', brand='Brand'),
        product('juliette', name='Juliette EDP', brand='Juliette Has a Gun'),
        product('vanilla', name='Juliette Has a Gun Vanilla Vibes EDP', brand='Juliette Has a Gun'),
        product('ego100', name='Ego stratis edp 100 ml', brand='Juliette Has a Gun'),
        product('ego50', name='Ego stratis edp 50 ml', brand='Juliette Has a Gun'),
    ]


@pytest.mark.parametrize('query,identifier', [
    ('Parlami di Orange Crush Eau de Parfum', 'orange_edp'),
    ('Parlami di Orange Crush EDP', 'orange_edp'),
    ('Parlami di Angel Dust Extrait de Parfum', 'angel_extrait'),
    ('Parlami di Signature Costa Azzurra EDP', 'costa'),
    ('Parlami di Juliette Has a Gun Vanilla Vibes EDP', 'vanilla'),
    ('Parlami di Vanilla Vibes', 'vanilla'),
    ('Parlami di Ego stratis edp 50 ml', 'ego50'),
    ('Parlami di EGO STRATIS EAU DE PARFUM 50ml!', 'ego50'),
])
def test_specific_names_and_metadata_are_independent_of_catalog_order(query, identifier):
    for catalog in [perfumes(), list(reversed(perfumes()))]:
        match = ProductIdentity(catalog).resolve(query)
        assert match.status == 'matched'
        assert match.products[0]['id'] == identifier


def test_brands_disambiguate_identical_names():
    catalog = [product('a', name='Signature EDP', brand='Alpha'), product('b', name='Signature EDP', brand='Beta')]
    resolver = ProductIdentity(catalog)
    assert resolver.resolve('Parlami di Signature EDP').status == 'ambiguous'
    assert resolver.resolve('Parlami di Signature EDP di Beta').products[0]['id'] == 'b'


@pytest.mark.parametrize('query', ['Parlami di Ego Stratis 200 ml', 'Parlami di Orange Crush EDT'])
def test_explicit_unavailable_metadata_never_falls_back(query):
    assert ProductIdentity(perfumes()).resolve(query).status == 'unavailable'


def test_multiple_tagged_variants_do_not_establish_the_selected_size():
    resolver = ProductIdentity([product(name='Ego Stratis EDP', tags=['50 ml', '100 ml'])])
    assert resolver.resolve('Parlami di Ego Stratis 50 ml').status == 'unavailable'


def test_accents_punctuation_and_decimal_sizes_are_normalized():
    resolver = ProductIdentity([product(name="L'Été Extrait 7,5 ml", ptype='Extrait')])
    assert resolver.resolve('Parlami di l ete extrait 7.5ml').status == 'matched'
    assert name_text('100ml') == name_text('100 ml')


def test_olfactory_preferences_do_not_select_short_named_products():
    resolver = ProductIdentity([product(name='Vaniglia EDP'), product('p2', name='Rosa')])
    for query in ['cerco un profumo alla vaniglia', 'con rosa', 'senza rosa', 'con note di vaniglia', 'non mi piace rosa']:
        assert resolver.resolve(query).status == 'none'


def test_typos_only_offer_confirmation_for_explicit_information_requests():
    resolver = ProductIdentity(perfumes())
    assert resolver.resolve('Parlami di Orange Crsh').status == 'suggestions'
    assert resolver.resolve('Cerco qualcosa di fresco').status == 'none'


def test_full_catalog_names_never_silently_resolve_to_another_product():
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/catalog.json').read_text(encoding='utf-8'))
    resolver = ProductIdentity(catalog)
    for item in catalog:
        result = resolver.resolve('Parlami di ' + item['name'])
        assert result.status in ('matched', 'ambiguous'), (item['name'], result.status)
        assert item['id'] in {candidate['id'] for candidate in result.products}, item['name']
        if result.status == 'matched':
            assert result.products[0]['id'] == item['id']


def test_ambiguity_is_local_and_choice_survives_restart(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    first = client_advise(advisor, 'Parlami di Orange Crush', 'customer')
    assert first['products'] == [] and len(first['options']) == 2
    advisor._chat_completion.assert_not_called()
    advisor.search_engine.search.assert_not_called()
    pending = advisor.session_store.get_session('customer')['guided_state']['pending_product_choice']
    assert set(pending['ids']) == {'orange_edp', 'orange_extrait'}
    restarted = advisor_for(tmp_path, list(reversed(perfumes())))
    label = next(label for label in first['options'] if 'Extrait' in label)
    selected = client_advise(restarted, label, 'customer')
    assert selected['products'][0]['name'] == 'Orange Crush Extrait de Parfum'
    state = restarted.session_store.get_session('customer')
    assert state['active_perfume']['id'] == 'orange_extrait'
    assert 'pending_product_choice' not in state['guided_state']
    follow = client_advise(restarted, 'quanto costa?', 'customer')
    assert follow['products'] == []
    assert restarted.session_store.get_session('customer')['active_perfume']['id'] == 'orange_extrait'


def test_metadata_hint_selects_pending_product(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    client_advise(advisor, 'Parlami di Ego Stratis', 'customer')
    result = client_advise(advisor, '50 ml', 'customer')
    assert result['products'][0]['name'] == 'Ego stratis edp 50 ml'


def test_named_budget_survives_clarification_and_is_not_a_note_preference(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    response = client_advise(advisor, 'Vorrei Orange Crush sotto 50€', 'customer')
    label = next(label for label in response['options'] if 'Eau de Parfum' in label)
    result = client_advise(advisor, label, 'customer')
    assert result['products'] == []
    advisor._chat_completion.assert_not_called()
    prefs = advisor.session_store.get_session('customer')['guided_state']['preferences']
    assert prefs['max_price'] == 49.99
    assert prefs.get('required_notes', []) == []


def test_erasing_names_preserves_currency_decimals_and_other_notes():
    item = product(name='Vanilla Vibes Eau de Parfum', brand='Juliette Has a Gun')
    text = ProductIdentity([item]).erase_mentions('Vorrei Vanilla Vibes EDP tra 100,50 e 150,75 euro con iris', item)
    assert '100,50' in text and '150,75' in text and 'iris' in text
    assert 'vanilla' not in text and 'edp' not in text


def test_explicit_new_search_retires_old_choices(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    client_advise(advisor, 'Parlami di Orange Crush', 'customer')
    client_advise(advisor, 'cerco un profumo con iris', 'customer')
    assert 'pending_product_choice' not in advisor.session_store.get_session('customer')['guided_state']


def test_switch_between_identical_names_uses_product_id(tmp_path):
    catalog = [product('alpha', name='Signature EDP', brand='Alpha'), product('beta', name='Signature EDP', brand='Beta')]
    advisor = advisor_for(tmp_path, catalog)
    client_advise(advisor, 'Parlami di Signature EDP di Alpha', 'customer')
    response = client_advise(advisor, 'Parlami di Signature EDP di Beta', 'customer')
    assert response['products'][0]['brand'] == 'Beta'
    assert advisor.session_store.get_session('customer')['active_perfume']['id'] == 'beta'


def test_normalized_duplicate_labels_are_not_arbitrarily_numbered(tmp_path):
    catalog = [product('a', name='Été EDP'), product('b', name='Ete EDP')]
    advisor = advisor_for(tmp_path, catalog)
    result = client_advise(advisor, 'Parlami di Ete EDP', 'customer')
    assert result['products'] == [] and result['options'] == []
    advisor._chat_completion.assert_not_called()


def test_retry_and_failed_confirmation_preserve_atomic_dialog_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import src.main as api
    from src.chat_budget import ChatUnavailable
    advisor = advisor_for(tmp_path, perfumes())
    monkeypatch.setattr(api, 'advisor', advisor)
    api.rate_limiter.reset()
    client = TestClient(api.app)
    payload = {'message': 'Parlami di Orange Crush', 'session_id': 'customer', 'session_key': 'b' * 64, 'request_id': 'req_1'}
    first = client.post('/chat', json=payload)
    assert first.status_code == 200
    assert client.post('/chat', json=payload).json() == first.json()
    state = advisor.session_store.get_session('customer')
    selected = {**payload, 'message': first.json()['options'][0], 'request_id': 'req_2', 'session_context': first.json()['session_context']}
    original = advisor._chat_completion.side_effect
    advisor._chat_completion.side_effect = ChatUnavailable('llm_unavailable')
    assert client.post('/chat', json=selected).status_code == 503
    assert advisor.session_store.get_session('customer') == state
    advisor._chat_completion.side_effect = original
    completed = client.post('/chat', json=selected)
    assert completed.status_code == 200
    assert client.post('/chat', json=selected).json() == completed.json()


def test_disappeared_pending_choice_does_not_select_another_item(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    result = client_advise(advisor, 'Parlami di Orange Crush', 'customer')
    label = next(label for label in result['options'] if 'Extrait' in label)
    updated = advisor_for(tmp_path, [p for p in perfumes() if p['id'] != 'orange_extrait'])
    response = client_advise(updated, label, 'customer')
    assert response['products'] == []
    assert 'non è più disponibile' in response['reply']
    updated._chat_completion.assert_not_called()


def test_alternative_reference_is_preserved_after_clarification(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    first = client_advise(advisor, 'Una alternativa a Orange Crush massimo 95 euro', 'customer')
    label = next(label for label in first['options'] if 'Extrait' in label)
    result = client_advise(advisor, label, 'customer')
    assert result['products']
    assert all(p['name'] != 'Orange Crush Extrait de Parfum' and p['price'] <= 95 for p in result['products'])


def test_named_information_can_interrupt_quiz_without_becoming_an_answer(tmp_path):
    advisor = advisor_for(tmp_path, perfumes())
    client_advise(advisor, 'guidami', 'customer')
    result = client_advise(advisor, 'Parlami di Orange Crush', 'customer')
    assert result['products'] == [] and len(result['options']) == 2
    state = advisor.session_store.get_session('customer')['guided_state']
    assert state['step'] is None and state['answers'] == []


def test_millesime_can_be_omitted_but_explicit_title_takes_priority():
    resolver = ProductIdentity([product('a', name='Iris Debonair Millésime'), product('b', name='Iris Debonair EDP')])
    assert resolver.resolve('Parlami di Iris Debonair').status == 'ambiguous'
    assert resolver.resolve('Parlami di Iris Debonair Millésime').products[0]['id'] == 'a'


def test_concentration_punctuation_and_brand_words_do_not_conflict():
    resolver = ProductIdentity([product(name='Ambre Russe EDP', brand="Parfum d'Empire")])
    for query in ["Parlami di Parfum d'Empire Ambre Russe", 'Parlami di Ambre Russe Eau-de-Parfum', 'Parlami di Ambre Russe Eau.de.Parfum']:
        assert resolver.resolve(query).status == 'matched'


def test_explicit_multiple_versions_require_clarification():
    resolver = ProductIdentity(perfumes())
    assert resolver.resolve('Parlami di Orange Crush EDP e Extrait').status == 'ambiguous'
    assert resolver.resolve('Parlami di Ego Stratis EDP 50 ml e 100 ml').status == 'ambiguous'


def test_label_does_not_repeat_brand_already_in_title():
    item = product(name='Juliette Has a Gun Vanilla Vibes EDP', brand='Juliette Has a Gun')
    assert ProductIdentity.label(item) == item['name']


@pytest.mark.parametrize('name', ['Guidance Edp', 'Guidance 46 Extrait 100 ml'])
def test_guidance_is_not_a_quiz_restart_command(tmp_path, name):
    advisor = advisor_for(tmp_path, [product(name=name)])
    result = client_advise(advisor, 'Parlami di ' + name, 'customer')
    assert result['step'] is None
    assert result['products'][0]['name'] == name


def test_all_catalog_titles_through_real_advisor_flow(tmp_path):
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/catalog.json').read_text(encoding='utf-8'))
    advisor = advisor_for(tmp_path, catalog)
    resolver = ProductIdentity(catalog)
    for index, item in enumerate(catalog):
        result = client_advise(advisor, 'Parlami di ' + item['name'], f'catalog_customer_{index}')
        match = resolver.resolve('Parlami di ' + item['name'])
        if match.status == 'matched':
            assert result['products'] and result['products'][0]['name'] == item['name'], item['name']
            assert advisor.session_store.get_session(f'catalog_customer_{index}')['active_perfume']['id'] == item['id']
        else:
            assert match.status == 'ambiguous' and result['products'] == [], item['name']
