"""Persistent enrichment queue and bounded nightly processing; no Shopify calls."""
import argparse
import copy
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from src.catalog_integrity import BASE_DIR, atomic_write_json, validate_catalog
    from src.catalog_enrichment import (EnrichmentBatch, enrich_catalog_fields,
        enrichment_signature, reusable_enrichment, cache_enrichment)
    from src.ingest import KNOWN_FAMILIES, _get_groq_client, clean_single_note, is_valid_note_item, build_semantic_text
    from src.llm_resilience import InvalidCompletion
except ModuleNotFoundError:
    from catalog_integrity import BASE_DIR, atomic_write_json, validate_catalog
    from catalog_enrichment import (EnrichmentBatch, enrich_catalog_fields,
        enrichment_signature, reusable_enrichment, cache_enrichment)
    from ingest import KNOWN_FAMILIES, _get_groq_client, clean_single_note, is_valid_note_item, build_semantic_text
    from llm_resilience import InvalidCompletion

STATE_NAME = "catalog_enrichment_state.json"
logger = logging.getLogger("fragrance_advisor.catalog.jobs")


def utc_now():
    return datetime.now(timezone.utc)


def load_state(directory):
    path = Path(directory) / STATE_NAME
    if not path.exists():
        return {"version": 1, "queue": {}, "reservations": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("version") != 1
            or not isinstance(state.get("queue"), dict) or not isinstance(state.get("reservations"), list)):
        raise ValueError("Stato arricchimento non valido: non azzero automaticamente il budget.")
    for record in state["reservations"]:
        if (not isinstance(record, dict) or not isinstance(record.get("tokens"), int)
                or isinstance(record["tokens"], bool) or record["tokens"] < 0):
            raise ValueError("Registro token non valido.")
        try:
            timestamp = datetime.fromisoformat(record["at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Timestamp del registro token non valido.") from exc
        if timestamp.utcoffset() is None:
            raise ValueError("Timestamp del registro token privo di fuso orario.")
    for entry in state["queue"].values():
        if (not isinstance(entry, dict) or not isinstance(entry.get("attempts"), int)
                or isinstance(entry["attempts"], bool) or entry["attempts"] < 0
                or not isinstance(entry.get("status"), str)):
            raise ValueError("Voce della coda arricchimento non valida.")
    return state


def context_args(context):
    return (context["name"], context["brand"], context["description"], context["tags"],
            context["pyramid"], context["family"], KNOWN_FAMILIES)


def reconcile(state, catalog, out_of_stock):
    queue = {}
    for product in catalog + out_of_stock:
        identifier = product["id"]
        context = product.get("enrichment_input")
        if not isinstance(context, dict):
            queue[identifier] = {"status": "awaiting_sync", "signature": None, "attempts": 0}
            continue
        signature = enrichment_signature(*context_args(context))
        previous = state["queue"].get(identifier, {})
        entry = copy.deepcopy(previous) if previous.get("signature") == signature else {
            "signature": signature, "status": "pending", "attempts": 0}
        cached = reusable_enrichment(product, signature, context["description"], context["tags"], KNOWN_FAMILIES)
        if cached is not None:
            entry["status"] = "completed" if cached["notes"] or cached["family"] else "no_information"
        elif context["family"] and all(context["pyramid"].values()):
            entry["status"] = "not_needed"
        elif not context["description"].strip() and not context["tags"]:
            entry["status"] = "no_source"
        elif product.get("in_stock") is not True:
            entry["status"] = "out_of_stock"
        elif entry["status"] in ("out_of_stock", "awaiting_sync", "not_needed", "no_source"):
            entry["status"] = "pending"
        queue[identifier] = entry
    state["queue"] = queue
    cutoff = utc_now() - timedelta(hours=24)
    state["reservations"] = [record for record in state["reservations"]
                              if datetime.fromisoformat(record["at"]) > cutoff]
    return state


def refresh_queue(directory, catalog, out_of_stock):
    state = reconcile(load_state(directory), catalog, out_of_stock)
    atomic_write_json(Path(directory) / STATE_NAME, state)
    pending = sum(entry["status"] in ("pending", "failed") for entry in state["queue"].values())
    print(f"Coda arricchimento: {pending} prodotti disponibili da elaborare; nessuna chiamata LLM durante la sincronizzazione.")
    return state


def apply_result(product, result, signature):
    """Rebuild from deterministic fields, preserving current prices and availability."""
    context = product["enrichment_input"]
    updated = copy.deepcopy(product)
    updated["olfactory_pyramid"] = copy.deepcopy(context["pyramid"])
    updated["family"] = context["family"]
    updated["family_inference"] = None
    updated["unpositioned_notes"] = []
    provenance = copy.deepcopy(context["provenance"])
    provenance["llm_notes"] = []
    missing = {section for section, notes in updated["olfactory_pyramid"].items() if not notes}
    seen = {note.casefold() for notes in updated["olfactory_pyramid"].values() for note in notes}
    for note in result["notes"]:
        name = clean_single_note(note["name"])
        if not is_valid_note_item(name) or name.casefold() in seen:
            continue
        section = note["position"]
        if section is None:
            updated["unpositioned_notes"].append(name)
        elif section in missing:
            updated["olfactory_pyramid"][section].append(name)
            provenance["pyramid"][section] = {"source": "llm", "kind": "extracted"}
        else:
            continue
        seen.add(name.casefold())
        provenance["llm_notes"].append(dict(note, name=name, method="llm", kind="extracted"))
    family = result["family"]
    if not updated["family"] and family:
        if family["kind"] == "explicit":
            updated["family"] = family["value"]
            provenance["family"] = dict(family, method="llm")
        else:
            updated["family_inference"] = dict(family, method="llm")
    updated["data_provenance"] = provenance
    updated["enrichment_cache"] = cache_enrichment(signature, result)
    updated["semantic_text"] = build_semantic_text(updated)
    return updated


class NightlyBudget(EnrichmentBatch):
    """Persist conservative reservations before every call, including retries."""
    def __init__(self, state, directory, token_limit=40000, minute_target=4000, duration=1200):
        super().__init__()
        self.state, self.directory = state, Path(directory)
        self.token_limit, self.minute_target = token_limit, minute_target
        self.deadline = time.monotonic() + duration
        self.stop_reason = None
        self.current_reservation = None

    def persist(self):
        atomic_write_json(self.directory / STATE_NAME, self.state)

    def reserve_request(self, kwargs):
        # A UTF-8 byte bound deliberately overestimates input tokens; reserved
        # completion includes reasoning. Failed calls retain their reservation.
        estimate = sum(len(message["content"].encode("utf-8")) + 64 for message in kwargs["messages"])
        estimate += kwargs.get("max_tokens", 2048) + 128
        if estimate > 8000:
            raise InvalidCompletion("request_too_large")
        now = utc_now()
        records = [record for record in self.state["reservations"]
                   if datetime.fromisoformat(record["at"]) > now - timedelta(hours=24)]
        self.state["reservations"] = records
        if sum(record["tokens"] for record in records) + estimate > self.token_limit:
            self.stop_reason = "daily_budget"
            return False
        wait = 0.0
        if records:
            previous = records[-1]
            elapsed = (now - datetime.fromisoformat(previous["at"])).total_seconds()
            wait = max(0.0, previous["tokens"] * 60 / self.minute_target - elapsed)
        # Check the provider's 8K rolling minute bound as well as our average pace.
        recent = [record for record in records if datetime.fromisoformat(record["at"]) > now - timedelta(seconds=60)]
        if sum(record["tokens"] for record in recent) + estimate > 8000:
            wait = max(wait, max(60 - (now - datetime.fromisoformat(record["at"])).total_seconds() for record in recent))
        if time.monotonic() + wait + 25 > self.deadline:
            self.stop_reason = "time_budget"
            return False
        while wait > 0:
            interval = min(wait, 20.0)
            time.sleep(interval)
            wait -= interval
        record = {"at": utc_now().isoformat(), "tokens": estimate, "actual_tokens": None}
        self.state["reservations"].append(record)
        self.current_reservation = record
        self.persist()
        return True

    def record_usage(self, response):
        usage = getattr(response, "usage", None)
        actual = getattr(usage, "total_tokens", None)
        if isinstance(actual, int) and not isinstance(actual, bool) and actual >= 0 and self.current_reservation:
            self.current_reservation["actual_tokens"] = actual
            self.current_reservation["tokens"] = max(self.current_reservation["tokens"], actual)
            self.persist()


def read_products(path):
    if not path.exists():
        return []
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, list):
        raise ValueError(f"Dataset non valido: {path.name}")
    return result


def run_nightly(directory=None, client=None, max_products=30, token_limit=40000, duration=1200):
    directory = Path(directory or BASE_DIR / "data")
    catalog = read_products(directory / "catalog.json")
    unavailable = read_products(directory / "out_of_stock.json")
    validate_catalog(catalog)
    state = refresh_queue(directory, catalog, unavailable)
    batch = NightlyBudget(state, directory, token_limit=token_limit, duration=duration)
    now = utc_now().isoformat()
    candidates = [(index, product) for index, product in enumerate(catalog)
                  if state["queue"][product["id"]]["status"] in ("pending", "failed")
                  and state["queue"][product["id"]].get("next_attempt_at", "") <= now]
    # Untouched products first, then rotate failed requests by last attempt.
    candidates.sort(key=lambda pair: (state["queue"][pair[1]["id"]].get("attempts", 0),
                                     state["queue"][pair[1]["id"]].get("last_attempt_at", ""), pair[1]["id"]))
    if not candidates:
        print("Nessun prodotto disponibile da arricchire; zero chiamate Groq.")
        return state
    client = client or _get_groq_client()
    if client is None:
        raise ValueError("GROQ_API_KEY richiesta per l'arricchimento notturno.")
    for index, product in candidates[:max_products]:
        if batch.suspended or time.monotonic() + 25 > batch.deadline:
            break
        entry = state["queue"][product["id"]]
        before = len(state["reservations"])
        result = enrich_catalog_fields(client, *context_args(product["enrichment_input"]), batch)
        if batch.stop_reason:
            break
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["last_attempt_at"] = utc_now().isoformat()
        if result.get("successful"):
            catalog[index] = apply_result(product, result, entry["signature"])
            validate_catalog(catalog)
            atomic_write_json(directory / "catalog.json", catalog)
            entry["status"] = "completed" if result["notes"] or result["family"] else "no_information"
            entry.pop("next_attempt_at", None)
            entry.pop("last_error", None)
        else:
            kind, hint = batch.last_failure or ("invalid_response", None)
            entry["last_error"] = kind
            entry["status"] = "needs_review" if kind == "request_too_large" else "failed"
            cooldown = max(hint or 0, min(7 * 86400, 86400 * 2 ** min(entry["attempts"] - 1, 3)))
            entry["next_attempt_at"] = (utc_now() + timedelta(seconds=cooldown)).isoformat()
        batch.persist()
        logger.info("Prodotto %s: %s; %s chiamate API.", product["id"], entry["status"], len(state["reservations"]) - before)
    reserved = sum(record["tokens"] for record in state["reservations"])
    actual = sum(record.get("actual_tokens") or 0 for record in state["reservations"])
    print(f"Arricchimento: {batch.requests} prodotti tentati, {batch.failed} fallimenti; "
          f"token riservati nelle 24h: {reserved}/{token_limit}; token effettivi riportati: {actual}; "
          f"arresto: {batch.stop_reason or ('errori ripetuti' if batch.suspended else 'fine gruppo')}.")
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-products", type=int, default=30)
    parser.add_argument("--token-budget", type=int, default=40000)
    parser.add_argument("--max-minutes", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.max_products <= 30 or not 1 <= args.token_budget <= 40000 or not 1 <= args.max_minutes <= 20:
        parser.error("Limiti massimi: 30 prodotti, 40000 token e 20 minuti.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_nightly(max_products=args.max_products, token_limit=args.token_budget, duration=args.max_minutes * 60)


if __name__ == "__main__":
    main()
