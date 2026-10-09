"""Deterministic product mentions: names, brands, concentrations and declared sizes."""
import re
from dataclasses import dataclass
from difflib import get_close_matches

try:
    from src.recommendation_preferences import normalized
except ModuleNotFoundError:
    from recommendation_preferences import normalized


CONCENTRATIONS = re.compile(r"\b(?:extrait(?:[\W_]+de[\W_]+parfum)?|eau[\W_]+de[\W_]+parfum|eau[\W_]+de[\W_]+toilette|eau[\W_]+de[\W_]+cologne|edp|edt|edc|parfum)\b")
LABELS = {'extrait': 'extrait', 'extrait de parfum': 'extrait', 'eau de parfum': 'edp',
          'eau de toilette': 'edt', 'eau de cologne': 'edc', 'parfum': 'parfum',
          'edp': 'edp', 'edt': 'edt', 'edc': 'edc'}
SIZES = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*ml\b")
NAMED_REQUEST = re.compile(r"\b(?:parlami di|descrivi|informazioni su|quanto costa|quanto viene|prezzo di)\s+(.+)")


def name_text(value):
    text = normalized(value)
    text = CONCENTRATIONS.sub(lambda match: LABELS[re.sub(r'[\W_]+', ' ', match.group())], text)
    text = SIZES.sub(lambda match: format(float(match.group(1).replace(',', '.')), 'g').replace('.', 'p') + ' ml', text)
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', text)).strip()


def sizes(value):
    return {float(match.group(1).replace(',', '.')) for match in SIZES.finditer(normalized(value))}


def concentrations(value):
    return {LABELS[re.sub(r'[\W_]+', ' ', match.group())] for match in CONCENTRATIONS.finditer(normalized(value))}


def occurrences(query, alias):
    return list(re.finditer(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', query)) if alias else []


@dataclass
class Mention:
    status: str = 'none'
    products: tuple = ()
    alias: str = ''


class ProductIdentity:
    def __init__(self, catalog):
        self.entries = []
        self.by_id = {product['id']: product for product in catalog}
        self.brands = {name_text(p.get('brand', '')) for p in catalog} - {''}
        self.brand_patterns = {brand: re.compile(r'(?<!\w)' + re.escape(brand) + r'(?!\w)') for brand in self.brands}
        for product in catalog:
            full = name_text(product['name'])
            core = re.sub(r'\b(?:edp|edt|edc|extrait|parfum|millesime)\b|\b\d+(?:p\d+)?\s*ml\b', ' ', full)
            core = re.sub(r'\s+', ' ', core).strip()
            brand = name_text(product.get('brand', ''))
            # Catalog titles may include the manufacturer; accept both forms.
            short = core[len(brand):].strip() if brand and core.startswith(brand + ' ') else core
            aliases = {full, core, short} - {''}
            self.entries.append({'product': product, 'full': full, 'core': short,
                                 'aliases': aliases, 'brand': brand,
                                 'patterns': [(alias, re.compile(r'(?<!\w)' + re.escape(alias) + r'(?!\w)')) for alias in aliases],
                                 'concentrations': concentrations(full.removeprefix(brand + ' ') if brand else full) or concentrations(product.get('ptype', '')),
                                 # Tags can list several Shopify variants: never infer the selected size from them.
                                 'sizes': sizes(product['name'])})

    def resolve(self, query, candidate_ids=None):
        text = name_text(query)
        brand_hits = [(match.start(), match.end(), brand) for brand, pattern in self.brand_patterns.items()
                      for match in pattern.finditer(text)]
        brand_hits = [hit for hit in brand_hits if not any(other[0] <= hit[0] and other[1] >= hit[1]
                      and other[1] - other[0] > hit[1] - hit[0] for other in brand_hits)]
        requested_brands = {hit[2] for hit in brand_hits}
        concentration_text = text
        for start, end, _ in sorted(brand_hits, reverse=True):
            concentration_text = concentration_text[:start] + ' ' * (end-start) + concentration_text[end:]
        requested_concentrations = concentrations(concentration_text)
        requested_sizes = sizes(query)
        entries = self.entries if candidate_ids is None else [e for e in self.entries if e['product']['id'] in candidate_ids]
        hits = []
        for entry in entries:
            for alias, pattern in entry['patterns']:
                if len(alias) < 3:
                    continue
                for match in pattern.finditer(text):
                    # A smell preference is not an explicit reference to a short product name.
                    prefix = text[:match.start()]
                    if alias == entry['core'] and ' ' not in alias and re.search(r'\b(?:con|senza|alla|al|note di|nota di|non voglio|non mi piace|evita)\s*$', prefix):
                        continue
                    hits.append((match.start(), match.end(), entry, alias))
        if hits:
            # Remove only nested shorter mentions, not independent names in comparisons.
            hits = [hit for hit in hits if not any(other[0] <= hit[0] and other[1] >= hit[1]
                    and other[1] - other[0] > hit[1] - hit[0]
                    and not ((len(requested_concentrations) > 1 or len(requested_sizes) > 1)
                             and other[2]['core'] == hit[2]['core']) for other in hits)]
            candidates = {hit[2]['product']['id']: hit[2] for hit in hits}
            alias = max((hit[3] for hit in hits), key=len)
        elif candidate_ids is not None:
            candidates = {e['product']['id']: e for e in entries}
            alias = ''
            if not (sizes(query) or concentrations(query) or any(pattern.search(text) for pattern in self.brand_patterns.values())):
                return Mention()
        else:
            # Only explicit information requests get typo suggestions, never automatic corrections.
            named = NAMED_REQUEST.search(text)
            if named:
                target = named.group(1).strip()
                aliases = {e['core'] for e in entries if len(e['core']) >= 4}
                close = get_close_matches(target, sorted(aliases), n=3, cutoff=0.88)
                proposed = tuple(e['product'] for e in entries if e['core'] in close)
                if proposed:
                    return Mention('suggestions', proposed, target)
            return Mention()
        filtered = [entry['product'] for entry in candidates.values()
                    if (not requested_brands or entry['brand'] in requested_brands)
                    and (not requested_concentrations or entry['concentrations'] & requested_concentrations)
                    and (not requested_sizes or entry['sizes'] & requested_sizes)]
        filtered.sort(key=lambda product: (name_text(product['name']), name_text(product.get('brand', '')), product['id']))
        if not filtered:
            return Mention('unavailable', (), alias)
        return Mention('matched' if len(filtered) == 1 else 'ambiguous', tuple(filtered), alias)

    @staticmethod
    def label(product):
        brand, name = product.get('brand', ''), product['name']
        return name if not brand or name_text(name).startswith(name_text(brand) + ' ') else f"{brand} — {name}"

    def erase_mentions(self, query, product):
        # Preserve price punctuation/currency and note language outside the product mention.
        text = normalized(query)
        entry = next((e for e in self.entries if e['product']['id'] == product['id']), None)
        if entry:
            for alias in sorted(entry['aliases'] | {name_text(product.get('brand', ''))}, key=len, reverse=True):
                if alias:
                    patterns = {'edp': r'(?:edp|eau\s+de\s+parfum)',
                                'edt': r'(?:edt|eau\s+de\s+toilette)',
                                'edc': r'(?:edc|eau\s+de\s+cologne)',
                                'extrait': r'extrait(?:\s+de\s+parfum)?'}
                    tokens = [patterns.get(token, re.escape(token).replace('p', '[.,]') if re.fullmatch(r'\d+p\d+', token) else re.escape(token)) for token in alias.split()]
                    pattern = r'[\W_]*'.join(tokens)
                    text = re.sub(r'(?<!\w)' + pattern + r'(?!\w)', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()
