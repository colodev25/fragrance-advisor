"""Commercial variant data, independent of model-generated product text."""
import re
from urllib.parse import urlsplit


def cart_product_fields(product):
    urls = product.get("urls", {})
    link = urls.get("add_to_cart", product.get("add_to_cart_url", ""))
    try:
        match = re.fullmatch(r"/(?:[a-zA-Z-]+/)?cart/([1-9][0-9]*):1", urlsplit(link).path)
    except (ValueError, TypeError):
        match = None
    linked_id = match.group(1) if match else ""
    declared = str(product.get("variant_id", ""))
    identifier = declared if re.fullmatch(r"[1-9][0-9]*", declared) else linked_id
    # Never pair a price/options record with a different purchase link.
    if declared and identifier != linked_id:
        identifier = ""
    title = product.get("variant_title", "")
    title = title.strip() if isinstance(title, str) else ""
    if title.casefold() == "default title":
        title = ""
    return {"variant_id": identifier, "variant_title": title}
