"""Constructed deck fingerprints in Untapped title-ID space; unknown IDs fail closed."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path


def fingerprint(deck):
    if not deck.get('main'):
        return None
    sections = {k: Counter(deck.get(k, [])) for k in ('main', 'side', 'commanders', 'companions')}
    # Sources may include the commander in the main count or list it separately.
    for role, area in (('commanders', 'main'), ('companions', 'side')):
        for card, count in sections[role].items():
            sections[area][card] = max(0, sections[area][card]-count)
    canonical = {k: sorted((int(card), n) for card, n in v.items() if n) for k, v in sections.items()}
    return 'title-v1:' + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:24]


@lru_cache(maxsize=1)
def title_mapping():
    path = Path(__file__).resolve().parents[1]/'data/untapped/cards-review.json'
    try:
        cards = json.loads(path.read_text(encoding='utf-8'))
        return {int(c['grpid']): int(c['titleId']) for c in cards}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def local_fingerprint(deck, mapping=None):
    mapping = title_mapping() if mapping is None else mapping
    result = {}
    try:
        for local, key in (('MainDeck', 'main'), ('Sideboard', 'side'),
                           ('CommandZone', 'commanders'), ('Companions', 'companions')):
            result[key] = []
            for card in deck.get(local) or []:
                quantity = int(card['quantity'])
                if not 0 < quantity <= 1000:
                    return None
                result[key].extend([mapping[int(card['cardId'])]]*quantity)
    except (KeyError, TypeError, ValueError):
        return None
    return fingerprint(result)
