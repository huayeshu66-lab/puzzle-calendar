"""Validate calendar information and draw prose or compact two-column fields.

This stdlib helper validates provenance contracts, not the truth of supplied
facts. It computes no lunar dates, holidays, weather, astrology or fortunes,
and never changes the planner's Gregorian dates. Origins and sources belong
inside module.provenance. Classification is retained in metadata and disclosed
in delivery notes; player pages carry no generated disclaimer labels.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
import unicodedata

FACTUAL = frozenset(('lunar', 'solar_term', 'holiday', 'observance',
                     'western_sign', 'chinese_zodiac', 'ganzhi', 'weather'))
ENTERTAINMENT = frozenset(('western_horoscope', 'eastern_fortune', 'almanac'))
AUTHORED = frozenset(('quote', 'custom'))
INPUTS = {'anniversary': 'user_input', 'habit': 'tracking'}
REGISTRY = FACTUAL | ENTERTAINMENT | AUTHORED | INPUTS.keys()
ENTERTAINMENT_MARK = '（娱乐）'


def _string(value, name, limit=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    if any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs') for char in value):
        raise ValueError(f'{name} contains control characters')
    if limit is not None and len(value) > limit:
        raise ValueError(f'{name} exceeds {limit} characters')
    return value


def _date(value):
    _string(value, 'date')
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('date must be a valid ISO YYYY-MM-DD date') from exc
    if parsed.isoformat() != value:
        raise ValueError('date must be a canonical ISO YYYY-MM-DD date')
    return value


def _module(module):
    if not isinstance(module, dict):
        raise ValueError('information module must be an object')
    result = copy.deepcopy(module)
    _string(result.get('module_id'), 'module_id')
    kind = _string(result.get('kind'), 'kind')
    if kind not in REGISTRY:
        raise ValueError(f'unknown information kind: {kind}')
    _string(result.get('title'), 'title', 50)
    if 'fields' in result:
        if 'text' in result:
            raise ValueError('use fields or text, not both')
        fields = result['fields']
        if not isinstance(fields, list) or not 1 <= len(fields) <= 6:
            raise ValueError('fields must contain 1 to 6 items')
        seen = set()
        for field in fields:
            if not isinstance(field, dict) or set(field) != {'label', 'value'}:
                raise ValueError('field requires exactly label and value')
            label = _string(field['label'], 'field label', 4)
            _string(field['value'], 'field value', 16)
            if label in seen:
                raise ValueError('duplicate field label')
            seen.add(label)
    else:
        _string(result.get('text'), 'text', 800)
    if 'origin' in result or 'source' in result:
        raise ValueError('origin and source must be nested inside provenance')
    proof = result.get('provenance', {})
    if 'attribution' in result:
        if kind!='quote':raise ValueError('attribution is only supported for quote modules')
        if 'fields' in result:raise ValueError('attributed quotes require text, not compact fields')
        _string(result['attribution'],'quote attribution',50)
    if not isinstance(proof, dict):
        raise ValueError('provenance must be an object')
    for key in ('status', 'source', 'method', 'origin'):
        if key in proof:
            _string(proof[key], f'provenance.{key}')
    if kind in FACTUAL:
        if proof.get('status') != 'verified':
            raise ValueError('factual provenance status must be verified')
        for key in ('source', 'method'):
            _string(proof.get(key), f'factual provenance.{key}')
        classification = 'factual'
    elif kind in ENTERTAINMENT or kind in AUTHORED:
        origins = {'user_supplied', 'attributed_source',
                   'original_entertainment' if kind in ENTERTAINMENT else 'original'}
        if proof.get('origin') not in origins:
            raise ValueError(f'{kind} requires a valid provenance.origin')
        if proof['origin'] == 'attributed_source':
            _string(proof.get('source'), 'attributed provenance.source')
        classification = 'entertainment' if kind in ENTERTAINMENT else 'authored'
        if kind in ENTERTAINMENT:
            title = result['title']
            while title.endswith(ENTERTAINMENT_MARK):
                title = title[:-len(ENTERTAINMENT_MARK)].rstrip()
            result['title'] = title
            _string(result['title'], 'title', 50)
    else:
        classification = INPUTS[kind]
        if proof.get('origin', classification) != classification:
            raise ValueError(f'{kind} provenance.origin must be {classification}')
        proof.setdefault('origin', classification)
    result['provenance'] = proof
    result['classification'] = classification
    return result


def prepare_information(full_document, payload):
    """Return validated modules by planned page ID without mutating inputs."""
    if payload is None:
        return {}
    if not isinstance(payload, dict) or payload.get('schema_version') != '1.0':
        raise ValueError('information requires schema_version 1.0')
    if not isinstance(payload.get('entries'), list):
        raise ValueError('information entries must be a list')
    try:
        pages = full_document['plan']['pages']
    except (KeyError, TypeError) as exc:
        raise ValueError('full calendar plan pages are required') from exc
    if not isinstance(pages, list):
        raise ValueError('full calendar plan pages must be a list')
    owned = {}
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get('dates'), list):
            raise ValueError('planned page dates must be a list')
        page_id = _string(page.get('page_id'), 'planned page_id')
        if page_id in owned:
            raise ValueError('duplicate planned page_id')
        owned[page_id] = {_date(value) for value in page['dates']}
    result = {}
    for entry in payload['entries']:
        if not isinstance(entry, dict):
            raise ValueError('information entry must be an object')
        page_id = _string(entry.get('page_id'), 'page_id')
        if page_id not in owned or page_id in result:
            raise ValueError('unknown or duplicate information page_id')
        if 'date' in entry and _date(entry['date']) not in owned[page_id]:
            raise ValueError('information date is not owned by its planned page')
        modules = entry.get('modules')
        if not isinstance(modules, list) or len(modules) > 8:
            raise ValueError('modules must be a list with at most 8 items per page')
        normalized, seen = [], set()
        for module in modules:
            item = _module(module)
            if item['module_id'] in seen:
                raise ValueError('duplicate information module_id on page')
            seen.add(item['module_id'])
            normalized.append(item)
        result[page_id] = normalized
    return result


def balanced_quote_lines(text,font,width,size):
    """Avoid a tiny second line in short quotes without changing any characters."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.units import mm
    measure=lambda value:pdfmetrics.stringWidth(value,font,size)/mm
    total=measure(text)
    if '\n' in text or total<=width or total>2*width:return text
    cut=max((i for i in range(1,len(text)) if measure(text[:i])<=width),default=0)
    if not cut or measure(text[cut:])>=width*.35:return text
    candidates=[]
    for i in range(1,len(text)):
        a,b=measure(text[:i]),measure(text[i:])
        if max(a,b)>width or min(a,b)<total*.30:continue
        if text[i] in '，。；：！？、）】》〉」』”’％%' or text[i-1] in '（【《〈「『“‘':continue
        priority=0 if text[i-1] in '。；！？' else 1 if text[i-1] in '，、：' else 2
        candidates.append((priority,abs(a-b),i))
    if not candidates:return text
    index=min(candidates)[2]
    return text[:index]+'\n'+text[index:]


def draw_information(page, modules, top, width, font_size=11, *, show_titles=False,left=None):
    """Draw prose or measured fields; never shrink or truncate to force a fit."""
    if not isinstance(modules, list) or len(modules) > 8:
        raise ValueError('modules must be a list with at most 8 items per page')
    for value in (top, width, font_size):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('information geometry must contain finite numbers')
    if top < 0 or width <= 0 or font_size < 11:
        raise ValueError('information geometry or font size is below minimum')
    x = page.safe[0] + 1 if left is None else left
    if type(x) not in (int,float) or not math.isfinite(x) or x<page.safe[0] or x+width>page.safe[2]:
        raise ValueError('information column must remain inside the safe area')
    for module in modules:
        item = _module(module)
        if show_titles:
            top += page.text(item['title'], x, top, 9.5,
                             role='information_title') + 3
        if 'fields' in item:
            top = _draw_fields(page, item['fields'], x, top, width, font_size) + 3
        else:
            original=page.font
            if item['kind']=='quote':page.font=getattr(page,'quote_font',original)
            try:
                text=balanced_quote_lines(item['text'],page.font,width,font_size) if item['kind']=='quote' else item['text']
                top = page.wrap(text, x, top, width, font_size,
                                role='information_text')
                if 'attribution' in item:
                    from reportlab.pdfbase import pdfmetrics
                    size=9.5
                    if pdfmetrics.stringWidth(item['attribution'],page.font,size)/ (72/25.4)>width:
                        raise ValueError('quote attribution does not fit at readable size')
                    top+=1
                    top+=page.text(item['attribution'],x+width,top,size,
                                   align='right',role='quote_attribution')
            finally:page.font=original
            top+=3
    return top


def _draw_fields(page, fields, x, top, width, font_size):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.units import mm

    gap, label_gap = 8, 3
    label_size = max(12, font_size)
    column_width = (width-gap)/2
    measured = []
    for field in fields:
        label = field['label'] + '：'
        label_width = pdfmetrics.stringWidth(label, page.font, label_size)/mm
        value_width = pdfmetrics.stringWidth(field['value'], page.font, font_size)/mm
        if label_width + label_gap + value_width + .1 > column_width:
            raise ValueError('compact information field does not fit its column; rewrite the value')
        measured.append((label, label_width, field['value']))
    label_widths = [max((item[1] for item in measured[col::2]),default=0) for col in (0,1)]
    for index, (_, _, value) in enumerate(measured):
        if label_widths[index%2]+label_gap+pdfmetrics.stringWidth(value,page.font,font_size)/mm+.1 > column_width:
            raise ValueError('aligned information field does not fit its column; rewrite the value')
    for offset in range(0, len(measured), 2):
        height = 0
        for column, (label, label_width, value) in enumerate(measured[offset:offset+2]):
            left = x + column*(column_width+gap)
            height = max(height, page.text(label, left, top, label_size,
                                           role='information_label', bold=True))
            height = max(height, page.text(value, left+label_widths[column]+label_gap, top, font_size,
                                           role='information_value'))
        top += height + 3
    return top
