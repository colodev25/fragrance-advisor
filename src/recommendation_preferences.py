"""Deterministic catalog evidence, conversational preferences and admission rules."""
import copy
import math
import re
import unicodedata
from decimal import Decimal


def normalized(text):
    return re.sub(r"\s+", " ", "".join(
        char for char in unicodedata.normalize("NFKD", str(text or "").casefold())
        if not unicodedata.combining(char)
    )).strip()


FAMILIES = {
    "agrumata": r"agrum\w*", "acquatica": r"acquat\w*|marin[oaie]",
    "aromatica": r"aromatic\w*", "verde": r"verd[ei]", "floreale": r"floreal\w*",
    "fruttata": r"fruttat\w*", "talcata": r"talcat\w*", "ambrata": r"ambrat\w*",
    "gourmand": r"gourmand", "orientale": r"oriental\w*", "vanigliata": r"vanigliat\w*",
    "legnosa": r"legnos\w*", "cuoiata": r"cuoiat\w*", "muschiata": r"muschiat\w*",
    "speziata": r"speziat\w*", "tabaccosa": r"tabaccos\w*", "chypre": r"chypre",
}
MACROS = {
    "fresco o agrumato": ["acquatica", "agrumata", "aromatica", "verde"],
    "floreale o fruttato": ["floreale", "fruttata", "talcata"],
    "dolce o caldo": ["ambrata", "gourmand", "orientale", "vanigliata"],
    "legnoso o intenso": ["chypre", "cuoiata", "legnosa", "muschiata", "speziata", "tabaccosa"],
}
BASE_NOTES = (
    "cannella vaniglia oud tabacco rosa iris gelsomino ambra bergamotto limone arancia cedro "
    "sandalo vetiver patchouli tonka pepe incenso cacao caffe mandorla fico sale mirra lavanda "
    "neroli tuberosa pesca mela pompelmo cuoio zenzero zafferano miele caramello muschio musk "
    "eliotropio ribes menta anice cocco lampone cardamomo"
).split() + ["pepe rosa", "chiodi di garofano", "noce moscata", "ambra grigia"]
NOTE_ALIASES = {"pink pepper": "pepe rosa", "rose": "rosa", "vanilla": "vaniglia",
                "cinnamon": "cannella", "jasmine": "gelsomino", "sandalwood": "sandalo",
                "cedarwood": "cedro", "bergamot": "bergamotto", "lemon": "limone",
                "incense": "incenso", "lavender": "lavanda", "ambergris": "ambra grigia"}
NOTE_ALIAS_PATTERN = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(alias) for alias in sorted(NOTE_ALIASES, key=lambda alias: -len(alias))) + r")(?!\w)")
NUMBER = r"(\d+(?:[.,]\d{1,2})?)(?![\d.,])"
NEGATION = re.compile(r"\b(?:senza|evita\w*|esclud\w*|niente|odio|non voglio|non mi piace|non mi piacciono|non deve contenere)\b")


def price_constraints(query, active=None):
    """Inclusive cent-based bounds; strict under/over are translated explicitly."""
    text = normalized(query)
    minimum = maximum = None
    spans = []
    ranges = [
        rf"\b(?:tra|fra|da)\s+(?:i\s+)?{NUMBER}\s*(?:€|euro)?\s*(?:e|a|-)\s*(?:i\s+)?{NUMBER}\s*(?:€|euro)?",
        rf"(?<!\w){NUMBER}\s*€\s*[-–]\s*{NUMBER}\s*(?:€|euro)",
    ]
    for pattern in ranges:
        match = re.search(pattern, text)
        if match:
            minimum, maximum = [float(value.replace(",", ".")) for value in match.groups()]
            spans.append(match.span())
            break
    if not spans:
        patterns = [
            ("max", False, rf"(?:\b(?:massimo|max|entro|fino a|budget(?: di)?|non(?: voglio spendere)? (?:piu di|oltre))\s+(?:i\s+)?|<=\s*){NUMBER}\s*(?:€|euro)?"),
            ("max", True, rf"(?:\b(?:sotto|meno di)\s+(?:i\s+)?|(?<![\w<])<(?![=])\s*){NUMBER}\s*(?:€|euro)?"),
            ("min", False, rf"(?:\b(?:almeno|minimo|min)\s+(?:i\s+)?|>=\s*){NUMBER}\s*(?:€|euro)?"),
            ("min", True, rf"(?:\b(?:sopra|oltre|piu di)\s+(?:i\s+)?|(?<![\w>])>(?![=])\s*){NUMBER}\s*(?:€|euro)?"),
        ]
        for direction, strict, pattern in patterns:
            for match in re.finditer(pattern, text):
                if any(match.start() < end and match.end() > start for start, end in spans):
                    continue
                value = Decimal(match.group(1).replace(",", "."))
                if strict:
                    value += Decimal("-0.01" if direction == "max" else "0.01")
                amount = float(value)
                if direction == "max":
                    maximum = amount if maximum is None else min(maximum, amount)
                else:
                    minimum = amount if minimum is None else max(minimum, amount)
                spans.append(match.span())
    if active and active.get("price") is not None:
        current = Decimal(str(active["price"]))
        if re.search(r"\b(piu economic\w*|meno costos\w*|piu abbordabile|piu accessibile|spendere meno|a meno|costa meno)\b", text):
            relative = float(current - Decimal("0.01"))
            maximum = relative if maximum is None else min(maximum, relative)
        if re.search(r"\b(piu costos\w*|piu pregiat\w*|spendere di piu)\b", text):
            relative = float(current + Decimal("0.01"))
            minimum = relative if minimum is None else max(minimum, relative)
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " + text[end:]
    return minimum, maximum, re.sub(r"\s+", " ", text).strip()


def recommendation_request(query):
    text = normalized(query)
    explicit_search = bool(re.search(r"\b(?:cerc\w*|alternativ\w*|consigli\w*|propon\w*|trov\w*)\b", text))
    if not explicit_search and re.search(r"^(?:(?:vorrei|voglio)\s+(?:sapere|capire|informazioni)|ha\b|contiene\b|e\b|questo\b|parlami\b|descrivi\b|quanto\b)", text):
        return False
    return bool(re.search(
        r"\b(?:cerc\w*|consigli\w*|propon\w*|mostr\w*|trov\w*|alternativ\w*|simile|divers\w*|"
        r"vorrei|voglio|senza|evita\w*|esclud\w*|niente|non mi piace|piu economic\w*|meno costos\w*)\b|^(?:ora )?(?:con|alla|al)\s+", text
    )) or price_constraints(text)[:2] != (None, None)


def recipient_evidence(name, tags, usage="", description=""):
    text = normalized(" ".join([name, *tags, usage or "", description or ""]))
    if re.search(r"\bunisex\b|\buomo e donna\b|sia per uomo che per donna", text):
        return "unisex"
    male = bool(re.search(r"\b(?:per lui|da uomo|uomo|maschile|for men|for him|pour homme|man|homme)\b", text))
    female = bool(re.search(r"\b(?:per lei|da donna|donna|femminile|for her|for women|pour femme|woman|women)\b", text))
    if male and female:
        evidence = normalized(" ".join([*tags, usage or "", description or ""]))
        both_declared = (bool(re.search(r"\b(?:uomo|per lui|maschile)\b", evidence)) and
                         bool(re.search(r"\b(?:donna|per lei|femminile)\b", evidence)))
        return "unisex" if both_declared else None
    return "male" if male else "female" if female else None


def family_values(text):
    value = normalized(text)
    return [family for family, pattern in FAMILIES.items() if re.search(rf"\b(?:{pattern})\b", value)]


def season_evidence(family, tags, usage="", description=""):
    text = normalized(" ".join([*tags, usage or "", description or ""]))
    summer = bool(re.search(r"\b(?:estiv\w*|estate|primaver\w*)\b", text))
    winter = bool(re.search(r"\b(?:invern\w*|inverno|autunn\w*)\b", text))
    if re.search(r"\b(?:quattro stagioni|tutte le stagioni|tutto l[' ]anno|ogni stagione)\b", text) or (summer and winter):
        return "all", "declared"
    if summer or winter:
        return ("summer" if summer else "winter"), "declared"
    families = set(family_values(family))
    summer = bool(families & {"acquatica", "agrumata", "verde"})
    winter = bool(families & {"cuoiata", "tabaccosa", "ambrata", "gourmand", "orientale", "speziata", "vanigliata"})
    if summer or winter:
        return ("all" if summer and winter else "summer" if summer else "winter"), "inferred"
    return None, "unknown"


def canonical_note(value):
    value = normalized(value)
    return NOTE_ALIAS_PATTERN.sub(lambda match: NOTE_ALIASES[match.group()], value)


def note_matches(requested, declared):
    requested, declared = canonical_note(requested), canonical_note(declared)
    # The rose flower and pink pepper must remain distinct.
    if requested == "rosa":
        declared = re.sub(r"\bpepe rosa\b", "", declared)
    return bool(re.search(rf"(?<!\w){re.escape(requested)}(?!\w)", declared))


class PreferenceMatcher:
    def __init__(self, catalog):
        self.catalog = catalog
        terms = set(BASE_NOTES) | set(NOTE_ALIASES)
        for product in catalog:
            pyramid = product.get("olfactory_pyramid", {})
            terms.update(normalized(note) for note in sum((pyramid.get(stage, []) for stage in ("top", "heart", "base")), [])
                         + product.get("unpositioned_notes", []) if isinstance(note, str) and note.strip())
        terms = {term for term in terms if not any(re.fullmatch(pattern, term) for pattern in FAMILIES.values())}
        self.note_pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in sorted(terms, key=lambda term: (-len(term), term))) + r")(?!\w)")
        self.facts = {product["id"]: self.product_facts(product) for product in catalog}

    def note_mentions(self, query):
        text = normalized(query)
        positive, negative = [], []
        previous_end = 0
        for match in self.note_pattern.finditer(text):
            prefix = text[:match.start()]
            prefix_start = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind("!"), prefix.rfind("?")) + 1
            negations = list(NEGATION.finditer(prefix, prefix_start))
            negated = bool(negations)
            if negated:
                negation = negations[-1]
                after = prefix[max(previous_end, negation.end()):]
                if re.search(r"\b(?:ma|pero|invece|con|alla|al|puoi includere)\b", after) and previous_end > negation.end():
                    negated = False
            if re.search(r"\bnon\s*$", prefix):
                negated = True
            if re.search(r"\bnon (?:solo|soltanto)\s*$", prefix):
                negated = False
            value = canonical_note(match.group())
            (negative if negated else positive).append((value, match.start(), match.end()))
            previous_end = match.end()
        return positive, negative

    def product_facts(self, product):
        pyramid = product.get("olfactory_pyramid", {})
        notes = sum((pyramid.get(stage, []) for stage in ("top", "heart", "base")), []) + product.get("unpositioned_notes", [])
        # Narrative evidence is used only for note mentions, never product/brand names.
        positive, _ = self.note_mentions(product.get("description", ""))
        notes = [normalized(note) for note in notes] + [note for note, *_ in positive]
        for tag in product.get("tags", []):
            value = normalized(tag)
            if self.note_pattern.fullmatch(value):
                notes.append(value)
        season, season_source = season_evidence(product.get("family", ""), product.get("tags", []),
                                                product.get("usage_profile", ""), product.get("description", ""))
        text = normalized(" ".join([*product.get("tags", []), product.get("usage_profile", ""), product.get("description", "")]))
        occasions = []
        if re.search(r"\b(?:ufficio|quotidian\w*|tutti i giorni|ogni giorno)\b", text):
            occasions.append("office")
        if re.search(r"\b(?:sera|serale|serata|occasioni speciali)\b", text):
            occasions.append("evening")
        return {"notes": list(dict.fromkeys(notes)), "families": family_values(product.get("family", "")),
                "inferred_families": family_values((product.get("family_inference") or {}).get("value", "")),
                "recipient": recipient_evidence(product.get("name", ""), product.get("tags", []), product.get("usage_profile", ""), product.get("description", "")),
                "season": season, "season_source": season_source, "occasion": occasions}

    def update(self, query, previous=None, active=None):
        prefs = copy.deepcopy(previous or {})
        text = normalized(query)
        positive, negative = self.note_mentions(text)
        clear_exclusions = bool(re.search(r"\b(?:nessuna esclusione|nessuna nota esclusa|rimuovi le esclusioni)\b", text))
        clear_required = bool(re.search(r"\b(?:nessuna nota obbligatoria|qualsiasi nota|nessuna preferenza sulle note)\b", text))
        unresolved = []
        for marker in NEGATION.finditer(text):
            tail = re.split(r"[.;!?]|\b(?:ma|pero|invece)\b", text[marker.end():], maxsplit=1)[0]
            if re.search(r"limite|budget|spendere|costos|economic|cara|caro", tail):
                continue
            for part in re.split(r",|\b(?:e|o)\b", tail):
                part = part.strip()
                if re.match(r"(?:con|al|alla)\b", part):
                    break
                generic_rejection = re.fullmatch(r"(?:(?:questo|questa|quel|quella|il|la) (?:profumo|fragranza)|questo|questa|quello|quella)", part)
                if part and not generic_rejection and not self.note_pattern.search(part) and not family_values(part) and not re.search(r"\bdolc[ei]\b", part):
                    unresolved.append(part[:80])
        if unresolved or negative or clear_exclusions or (NEGATION.search(text) and family_values(text)):
            prefs["unrecognized_exclusions"] = unresolved
        unresolved_positive = []
        clean_prices = price_constraints(text)[2]
        for marker in re.finditer(r"\b(?:con\s+(?:(?:note|accordi)\s+(?:di\s+)?)?|alla\s+|al\s+|all['’])", clean_prices):
            tail = re.split(r"[.;!?]|\b(?:ma|senza|evita\w*|non voglio|budget)\b", clean_prices[marker.end():], maxsplit=1)[0]
            if re.search(r"\b(?:prezzo|costo|budget|intensita|persistenza|scia|carattere|profilo)\b", tail):
                continue
            for part in re.split(r",|\b(?:e|o|oppure)\b", tail):
                part = part.strip()
                if part and not self.note_pattern.search(part) and not family_values(part) and not re.search(r"\b(?:dolc[ei]|fresc(?:o|a|hi|he))\b", part):
                    unresolved_positive.append(part[:80])
        if unresolved_positive or positive or clear_required:
            prefs["unrecognized_required_notes"] = unresolved_positive
        if clear_exclusions:
            prefs["excluded_notes"] = []
        exclusions = set(prefs.get("excluded_notes", []))
        for note, *_ in negative:
            exclusions.add(note)
        if positive:
            groups = []
            last_end = 0
            for note, start, end in positive:
                if groups and re.search(r"\b(?:o|oppure)\b", text[last_end:start]):
                    groups[-1].append(note)
                else:
                    groups.append([note])
                last_end = end
                exclusions.discard(note)
            prefs["required_notes"] = (prefs.get("required_notes", []) if re.search(r"\b(?:anche|aggiungi)\b", text) else []) + groups
        if negative:
            remaining = [[note for note in group if not any(note_matches(excluded, note) for excluded in exclusions)]
                         for group in prefs.get("required_notes", [])]
            prefs["required_notes"] = [group for group in remaining if group]
        if clear_required:
            prefs["required_notes"] = []
        prefs["excluded_notes"] = sorted(exclusions)
        minimum, maximum, _ = price_constraints(text, active)
        if re.search(r"\b(?:nessun limite(?: di budget)?|budget libero|senza limite di budget)\b", text):
            prefs.pop("min_price", None)
            prefs.pop("max_price", None)
        elif minimum is not None or maximum is not None:
            relative = bool(re.search(r"\b(?:piu economic\w*|meno costos\w*|piu abbordabile|piu accessibile|spendere meno|piu costos\w*|piu pregiat\w*)\b", text))
            if not relative:
                prefs.pop("min_price", None)
                prefs.pop("max_price", None)
            if minimum is not None:
                prefs["min_price"] = max(prefs.get("min_price", minimum), minimum)
            if maximum is not None:
                prefs["max_price"] = min(prefs.get("max_price", maximum), maximum)
        changed = []
        families = []
        excluded_families = set() if clear_exclusions else set(prefs.get("excluded_families", []))
        for family, pattern in FAMILIES.items():
            for match in re.finditer(rf"\b(?:{pattern})\b", text):
                prefix = re.split(r"[.;!?]|\b(?:ma|pero|invece|con)\b", text[:match.start()])[-1]
                if NEGATION.search(prefix) or re.search(r"\bnon\s*$", prefix):
                    excluded_families.add(family)
                else:
                    families.append(family)
                    excluded_families.discard(family)
        for label, values in MACROS.items():
            if label in text and not NEGATION.search(text[:text.index(label)]):
                families = values
                break
        sweet = re.search(r"\bdolc[ei]\b", text)
        if sweet and not families:
            if NEGATION.search(text[:sweet.start()]) or re.search(r"\bnon\s*$", text[:sweet.start()]):
                excluded_families.update(MACROS["dolce o caldo"])
            else:
                families = MACROS["dolce o caldo"]
        if not families and re.search(r"\bfresc(?:o|a|hi|he)\b", text):
            families = MACROS["fresco o agrumato"]
        if families:
            prefs["families"] = families
            changed.append("families")
        prefs["excluded_families"] = sorted(excluded_families)
        if prefs.get("families") and excluded_families:
            prefs["families"] = [family for family in prefs["families"] if family not in excluded_families]
            if not prefs["families"]:
                prefs.pop("families")
                prefs["strict"] = [key for key in prefs.get("strict", []) if key != "families"]
        recipient = recipient_evidence("", [], text)
        if recipient:
            prefs["recipient"] = recipient
            changed.append("recipient")
        season, source = season_evidence("", [], text)
        if source == "declared":
            prefs["season"] = season
            changed.append("season")
        if re.search(r"\b(?:ufficio|tutti i giorni|quotidian\w*)\b", text):
            prefs["occasion"] = "office"
            changed.append("occasion")
        elif re.search(r"\b(?:serata|sera|occasioni speciali)\b", text):
            prefs["occasion"] = "evening"
            changed.append("occasion")
        strict = set(prefs.get("strict", []))
        strict_text = re.sub(r"\bnon (?:solo|soltanto)\b", "", text)
        if re.search(r"\b(?:solo|esclusivamente|deve|obbligatoriamente|assolutamente)\b", strict_text):
            strict.update(changed)
        else:
            strict.difference_update(changed)
        prefs["strict"] = sorted(strict)
        for dimension, pattern in (("families", r"qualsiasi famiglia|nessuna preferenza olfattiva"),
                                   ("season", r"qualsiasi stagione|nessuna preferenza di stagione"),
                                   ("recipient", r"qualsiasi destinatario"), ("occasion", r"qualsiasi occasione")):
            if re.search(pattern, text):
                prefs.pop(dimension, None)
                prefs["strict"] = [key for key in prefs["strict"] if key != dimension]
        return prefs

    @staticmethod
    def bounds(prefs, api_max=None):
        maximum = prefs.get("max_price")
        if api_max is not None:
            maximum = float(api_max) if maximum is None else min(maximum, float(api_max))
        return prefs.get("min_price"), maximum

    def differences(self, product, prefs):
        facts = self.facts[product["id"]]
        differences = {}
        requested = set(prefs.get("families", []))
        if requested and not requested.intersection(facts["families"]):
            differences["families"] = "famiglia dedotta, non dichiarata" if requested.intersection(facts["inferred_families"]) else "famiglia olfattiva diversa o non dichiarata"
        recipient = prefs.get("recipient")
        if recipient and facts["recipient"] not in ({recipient, "unisex"} if recipient != "unisex" else {"unisex"}):
            differences["recipient"] = "destinatario diverso o non dichiarato"
        season = prefs.get("season")
        if season and (facts["season"] not in {season, "all"} or facts["season_source"] != "declared"):
            differences["season"] = "stagionalità dedotta dalla famiglia" if facts["season"] in {season, "all"} else "stagionalità diversa o non dichiarata"
        if prefs.get("occasion") and prefs["occasion"] not in facts["occasion"]:
            differences["occasion"] = "occasione d'uso non confermata dal catalogo"
        return differences

    def admitted(self, product, prefs, api_max=None):
        if prefs.get("unrecognized_exclusions") or prefs.get("unrecognized_required_notes"):
            return False
        price = product.get("price")
        if product.get("in_stock") is not True or not isinstance(price, (float, int)) or isinstance(price, bool) or not math.isfinite(price):
            return False
        minimum, maximum = self.bounds(prefs, api_max)
        if price < 0 or (minimum is not None and price < minimum) or (maximum is not None and price > maximum):
            return False
        notes = self.facts[product["id"]]["notes"]
        families = self.facts[product["id"]]["families"]
        if prefs.get("excluded_families") and (not families or set(prefs["excluded_families"]).intersection(families)):
            return False
        if prefs.get("excluded_notes") and (not notes or any(note_matches(note, item) for note in prefs["excluded_notes"] for item in notes)):
            return False
        if any(not any(note_matches(note, item) for note in group for item in notes) for group in prefs.get("required_notes", [])):
            return False
        strict = set(prefs.get("strict", []))
        return not strict or not strict.intersection(self.differences(product, prefs))

    def select(self, prefs, api_max=None, rank_ids=(), limit=5, excluded_ids=()):
        eligible = [(product, self.differences(product, prefs)) for product in self.catalog
                    if product["id"] not in excluded_ids and self.admitted(product, prefs, api_max)]
        exact = [pair for pair in eligible if not pair[1]]
        ranks = {identifier: index for index, identifier in reversed(list(enumerate(rank_ids)))}
        selected = sorted(exact or eligible, key=lambda pair: (
            len(pair[1]), ranks.get(pair[0]["id"], len(ranks)), pair[0]["id"]
        ))[:limit]
        return [product for product, _ in selected], {product["id"]: list(differences.values()) for product, differences in selected}


def selection_notice(products, differences, prefs):
    notices = []
    for product in products:
        reasons = differences.get(product["id"], [])
        if reasons:
            notices.append(f"{product['name']} è un'alternativa: {', '.join(reasons)}.")
    if prefs.get("excluded_notes"):
        notices.append("La selezione considera le note dichiarate a catalogo; le schede troppo incomplete sono escluse.")
    return "\n".join(notices)
