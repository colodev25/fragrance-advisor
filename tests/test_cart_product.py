from src.cart_product import cart_product_fields
from src import ingest


def test_legacy_permalink_recovers_only_variant_id():
    assert cart_product_fields({"urls": {"add_to_cart": "https://etualy.com/cart/123:1"}}) == {
        "variant_id": "123", "variant_title": ""}


def test_mismatched_variant_cannot_be_purchased_and_default_title_is_hidden():
    assert cart_product_fields({"variant_id": "456", "variant_title": "Default Title",
                                "urls": {"add_to_cart": "https://etualy.com/cart/123:1"}}) == {
        "variant_id": "", "variant_title": ""}


def test_ingestion_price_options_and_link_come_from_same_available_variant():
    raw = {'id': 1, 'title': 'Iris Eau de Parfum', 'vendor': 'Etualy', 'handle': 'iris',
           'body_html': '<p>Profumo con iris e sandalo.</p>', 'tags': [], 'images': []}
    raw['variants'] = [
        {'id': 1, 'price': '50', 'available': False, 'title': '30 ml', 'sku': 'small'},
        {'id': 2, 'price': '90', 'available': True, 'title': '50 ml', 'option1': '50 ml', 'sku': 'medium'},
    ]
    product = ingest.transform_product(raw, 'https://etualy.com', allow_llm=False)
    assert (product['variant_id'], product['variant_title'], product['variant_options'], product['price'], product['sku']) == (
        '2', '50 ml', ['50 ml'], 90, 'medium')
    assert product['urls']['add_to_cart'] == 'https://etualy.com/cart/2:1'
