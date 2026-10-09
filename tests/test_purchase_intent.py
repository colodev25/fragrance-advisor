import pytest

from src.purchase_intent import purchase_request, format_request, requested_size
from tests.test_recommendation_preferences import advisor_for, product
from tests.session_client import client_advise


@pytest.mark.parametrize('query', ['aggiungi al carrello Iris 100ml', 'Puoi aggiungere Iris al carrello?',
                                 'vorrei aggiungere questo profumo al carrello da 50 ml'])
def test_explicit_cart_requests(query):
    assert purchase_request(query)


@pytest.mark.parametrize('query', ['non aggiungere Iris al carrello', 'come aggiungere Iris al carrello?',
                                 'Iris mi piace', 'aggiungi al carrello Iris senza rosa'])
def test_questions_negations_and_exclusions_do_not_prepare_purchase(query):
    assert not purchase_request(query)


def test_size_and_format_questions():
    assert format_request('Quali formati sono disponibili per Iris?')
    assert requested_size('aggiungi Iris 7,5ml al carrello') == '7.5 ml'
    assert requested_size('50 ml oppure 100 ml') == ''


def test_named_purchase_preserves_shopify_size_not_declared_in_product_title(tmp_path):
    advisor = advisor_for(tmp_path, [product('iris', name='Iris Eau de Parfum')])
    response = client_advise(advisor, 'aggiungi al carrello Iris 100ml', 'customer')
    assert response['products'][0]['purchase_intent'] is True
    assert response['products'][0]['requested_size'] == '100 ml'
    assert 'Conferma aggiunta' in response['reply']
    advisor._chat_completion.assert_not_called()


def test_specific_size_price_question_uses_live_variant_card(tmp_path):
    advisor = advisor_for(tmp_path, [product('iris', name='Iris Eau de Parfum')])
    response = client_advise(advisor, 'Quanto costa Iris 100ml?', 'customer')
    assert response['products'][0]['requested_size'] == '100 ml'
    assert response['products'][0]['purchase_intent'] is False
    advisor._chat_completion.assert_not_called()


def test_active_product_can_prepare_purchase_but_unknown_name_cannot_reuse_it(tmp_path):
    advisor = advisor_for(tmp_path, [product('iris', name='Iris Eau de Parfum')])
    client_advise(advisor, 'Parlami di Iris', 'customer')
    response = client_advise(advisor, 'aggiungi al carrello questo da 100ml', 'customer')
    assert response['products'][0]['requested_size'] == '100 ml'
    wrong = client_advise(advisor, 'aggiungi al carrello Atlantis da 100ml', 'customer')
    assert wrong['products'] == []
    assert 'Quale profumo' in wrong['reply']


def test_ambiguous_product_choice_retains_purchase_and_requested_size(tmp_path):
    advisor = advisor_for(tmp_path, [product('a', name='Iris Eau de Parfum', brand='Alpha'),
                                   product('b', name='Iris Eau de Parfum', brand='Beta')])
    first = client_advise(advisor, 'aggiungi al carrello Iris 100 ml', 'customer')
    assert not first['products']
    second = client_advise(advisor, first['options'][1], 'customer')
    assert second['products'][0]['brand'] == 'Beta'
    assert second['products'][0]['purchase_intent'] is True
    assert second['products'][0]['requested_size'] == '100 ml'
    advisor._chat_completion.assert_not_called()


def test_formats_answer_uses_live_card_instead_of_inventing_sizes(tmp_path):
    advisor = advisor_for(tmp_path, [product('iris', name='Iris Eau de Parfum')])
    response = client_advise(advisor, 'Quali formati sono disponibili per Iris?', 'customer')
    assert response['products'][0]['purchase_intent'] is False
    assert '100 ml' not in response['reply']
    advisor._chat_completion.assert_not_called()


def test_generic_purchase_after_multiple_recommendations_requires_product_choice(tmp_path):
    catalog = [product('a', name='Iris Eau de Parfum'), product('b', name='Rose Eau de Parfum')]
    advisor = advisor_for(tmp_path, catalog)
    client_advise(advisor, 'Parlami di Iris', 'customer')
    saved = advisor.session_store.get_session('customer')
    saved['guided_state']['last_presented_product_ids'] = ['a', 'b']
    advisor.session_store.save_session('customer', saved['history'], saved['active_perfume'], saved['guided_state'])
    response = client_advise(advisor, 'aggiungi al carrello questo da 100ml', 'customer')
    assert response['products'] == []
    assert len(response['options']) == 2
