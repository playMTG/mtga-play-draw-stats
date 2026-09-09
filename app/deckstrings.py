"""Decode Untapped deckstring title IDs (not Arena grpIds).

Wire layout verified against Untapped's public web decoder: reserved byte,
version, delta-encoded commander/companion metadata, and counted card sections.
Unknown versions and truncated payloads fail closed; revealed creatures are
never inferred to be commanders.
"""
import base64
import binascii


def decode(value: str) -> dict:
    if not isinstance(value, str) or len(value) > 100000:
        raise ValueError('Invalid deckstring')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Invalid base64') from exc
    pos = 0

    def number():
        nonlocal pos
        n = 0
        for shift in range(0, 35, 7):
            if pos >= len(raw):
                raise ValueError('Truncated deckstring')
            b = raw[pos]; pos += 1
            n |= (b & 127) << shift
            if not b & 128:
                return n
        raise ValueError('Invalid varint')

    def group(quantity):
        count = number()
        if count > 10000:
            raise ValueError('Too many cards')
        out, title = [], 0
        for _ in range(count):
            qty = quantity if quantity is not None else number()
            if qty > 1000:
                raise ValueError('Invalid quantity')
            title += number()
            out.extend([title]*qty)
        return out

    def section():
        return [x for qty in (1,2,3,4,None) for x in group(qty)]

    if number() != 0:
        raise ValueError('Invalid marker')
    version = number()
    if version not in (2,3,4):
        raise ValueError('Unsupported deckstring version')
    result = {'commanders': [], 'companions': [], 'main': [], 'side': [], 'wish': []}
    if version == 2:
        result['commanders'] = group(1)
    else:
        count, title = number(), 0
        if count > 10000:
            raise ValueError('Invalid mechanics')
        for _ in range(count):
            title += number()
            mechanic = number()
            if mechanic not in (1,2):
                raise ValueError('Unsupported mechanic')
            result['commanders' if mechanic == 1 else 'companions'].append(title)
    if version == 4:
        seen = set()
        while True:
            tag = number()
            if tag == 0:
                break
            if tag not in (1,2,3) or tag in seen:
                raise ValueError('Invalid section')
            seen.add(tag)
            result[{1:'main',2:'side',3:'wish'}[tag]] = section()
    else:
        result['main'] = section()
        if number() == 1:
            result['side'] = section()
    if pos != len(raw):
        raise ValueError('Unexpected trailing bytes')
    return result
