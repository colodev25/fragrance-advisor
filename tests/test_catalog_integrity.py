"""Isolated catalog/generation tests without Shopify or embedding downloads."""
import copy
import json
from unittest.mock import MagicMock

import pytest

from src.catalog_integrity import (atomic_write_json, catalog_fingerprint,
                                   load_generation, validate_catalog)
from src.reindex import build_index


@pytest.fixture
def product():
    return {"id": "sh_1", "name": "Iris", "price": 100.0, "in_stock": True,
            "description": "Note di iris", "semantic_text": "Profumo di iris",
            "urls": {"product_page": "https://example.com/products/iris",
                     "add_to_cart": "https://example.com/cart/1:1"},
            "olfactory_pyramid": {"top": ["Iris"], "heart": [], "base": []}}


@pytest.mark.parametrize("field,value", [("id", ""), ("price", float("nan")),
    ("price", float("inf")), ("price", -1), ("price", True), ("name", " "),
    ("in_stock", False), ("olfactory_pyramid", {"top": "Iris"}),
    ("urls", {"product_page": "javascript:alert(1)", "add_to_cart": "https://example.com/cart"})])
def test_invalid_products_block_catalog(product, field, value):
    product[field] = value
    with pytest.raises(ValueError):
        validate_catalog([product])


def test_optional_missing_data_warns_and_duplicates_fail(product):
    assert validate_catalog([product])
    with pytest.raises(ValueError):
        validate_catalog([product, copy.deepcopy(product)])
    with pytest.raises(ValueError):
        validate_catalog([])


def test_fingerprint_ignores_product_and_key_order(product):
    second = dict(product, id="sh_2")
    assert catalog_fingerprint([product, second]) == catalog_fingerprint([second, dict(reversed(list(product.items())))])
    second["price"] = 200
    assert catalog_fingerprint([product]) != catalog_fingerprint([second])


def test_atomic_serialization_failure_preserves_file(tmp_path):
    target = tmp_path / "catalog.json"
    atomic_write_json(target, {"old": True})
    with pytest.raises(ValueError):
        atomic_write_json(target, {"price": float("nan")})
    assert json.loads(target.read_text()) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))


class Collection:
    def __init__(self):
        self.ids = []

    def add(self, ids, **kwargs):
        self.ids.extend(ids)

    def count(self):
        return len(self.ids)

    def get(self, **kwargs):
        return {"ids": self.ids}

    def query(self, **kwargs):
        return {"ids": [self.ids[:1]]}


def fake_client():
    client = MagicMock()
    client.create_collection.side_effect = lambda **kwargs: Collection()
    return client


def test_new_generation_removes_deleted_products_and_keeps_old_snapshot(tmp_path, product):
    source, root = tmp_path / "catalog.json", tmp_path / "chroma"
    second = dict(product, id="sh_2")
    atomic_write_json(source, [product, second])
    client = fake_client()
    factory = lambda **kwargs: client
    old = build_index(source, root, factory, lambda: None)
    atomic_write_json(source, [second])
    current = build_index(source, root, factory, lambda: None)
    assert old["collection"] != current["collection"]
    manifest, snapshot = load_generation(root)
    assert manifest == current
    assert [item["id"] for item in snapshot] == ["sh_2"]
    assert (root / "generations" / f'{old["generation"]}.json').exists()
    assert not (root / "reindex.lock").exists()


@pytest.mark.parametrize("failure", ["add", "count", "probe"])
def test_failed_build_keeps_active_generation(tmp_path, product, failure):
    source, root = tmp_path / "catalog.json", tmp_path / "chroma"
    atomic_write_json(source, [product])
    client = fake_client()
    old = build_index(source, root, lambda **kwargs: client, lambda: None)
    broken = MagicMock()
    broken.count.return_value = 0 if failure == "count" else 1
    broken.get.return_value = {"ids": [product["id"]]}
    broken.query.return_value = {"ids": [[]]}
    if failure == "add":
        broken.add.side_effect = RuntimeError("Embedding failed")
    client.create_collection.side_effect = None
    client.create_collection.return_value = broken
    with pytest.raises(RuntimeError):
        build_index(source, root, lambda **kwargs: client, lambda: None)
    assert load_generation(root)[0] == old
    assert not (root / "reindex.lock").exists()


def test_snapshot_tampering_is_rejected(tmp_path, product):
    source, root = tmp_path / "catalog.json", tmp_path / "chroma"
    atomic_write_json(source, [product])
    manifest = build_index(source, root, lambda **kwargs: fake_client(), lambda: None)
    product["price"] = 50
    atomic_write_json(root / "generations" / f'{manifest["generation"]}.json', [product])
    with pytest.raises(ValueError):
        load_generation(root)


def test_partial_shopify_download_raises(monkeypatch):
    from src import ingest
    monkeypatch.setattr(ingest, "PER_PAGE", 1)
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = {"products": [{"id": 1}]}
    session.get.side_effect = [response, RuntimeError("Network failure")]
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr(ingest.requests, "Session", lambda: context)
    with pytest.raises(RuntimeError, match="pagina 2"):
        ingest.fetch_all_shopify_products("https://example.com")


def test_invalid_ingestion_preserves_catalog(tmp_path, monkeypatch, product):
    from src import ingest
    target = tmp_path / "catalog.json"
    atomic_write_json(target, [product])
    monkeypatch.setattr(ingest, "OUTPUT_FILE", target)
    monkeypatch.setattr(ingest, "fetch_all_shopify_products", lambda *args: [{"id": 1}])
    monkeypatch.setattr(ingest, "is_fragrance", lambda value: True)
    invalid = copy.deepcopy(product)
    invalid["price"] = -1
    invalid.update(family="", ptype="", usage_profile="")
    monkeypatch.setattr(ingest, "transform_product", lambda *args: invalid)
    with pytest.raises(ValueError):
        ingest.run_ingest()
    assert json.loads(target.read_text()) == [product]
