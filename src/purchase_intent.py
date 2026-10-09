"""Deterministic purchase preparation; cart writes remain explicit browser actions."""
import re

SIZE = re.compile(r'\b(\d+(?:[.,]\d+)?)\s*ml\b', re.I)


def purchase_request(query):
    text = query.strip().lower()
    return bool(re.match(r'^(?:per favore\s+)?(?:aggiungi|metti|inserisci|'
                         r'(?:puoi|potresti|vorrei|voglio)\s+(?:aggiungere|inserire|mettere))\b', text)
                and re.search(r'\bcarrello\b', text)
                and not re.search(r'\b(?:non|senza|evita)\b', text))


def format_request(query):
    return bool((re.search(r'\b(?:format\w*|tagli\w*|misur\w*)\b', query, re.I)
                 and re.search(r'\b(?:qual\w*|esist\w*|disponib\w*|mostr\w*|ha|sono)\b', query, re.I))
                or (SIZE.search(query) and re.match(r'^(?:quanto costa|prezzo di|esiste|esistono|[eè] disponibile)\b', query.strip(), re.I)))


def requested_size(query):
    values = {float(m.group(1).replace(',', '.')) for m in SIZE.finditer(query)}
    return f'{next(iter(values)):g} ml' if len(values) == 1 else ''


def refers_to_active(query):
    text = SIZE.sub(' ', query.lower())
    words = set(re.findall(r'\w+', text))
    return words <= {'aggiungi', 'aggiungere', 'metti', 'mettere', 'inserisci', 'inserire',
                     'al', 'nel', 'carrello', 'questo', 'quello', 'questa', 'quella', 'profumo',
                     'fragranza', 'formato', 'da', 'in', 'il', 'la', 'lo', 'stesso', 'vorrei',
                     'voglio', 'puoi', 'potresti', 'per', 'favore', 'una', 'confezione',
                     'quali', 'quale', 'formati', 'esistono', 'esiste', 'disponibili', 'disponibile',
                     'più', 'piu', 'sono', 'ha', 'tagli', 'misure', 'quanto', 'costa', 'prezzo', 'di', 'è', 'e'}
