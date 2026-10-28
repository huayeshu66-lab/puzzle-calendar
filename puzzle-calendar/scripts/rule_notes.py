"""Public rule summaries, conservative identities, and a separate full-rule PDF.

Summaries never replace the source rules or enter a puzzle's proof record. The
guide prints full public rules, with no clues, solutions, or personal metadata.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile

MM = 72 / 25.4
NAMES = {'sudoku': '数独', 'nonogram': '数织', 'maze': '迷宫'}
HITORI_RULES = (
    '涂黑部分数字，使剩余白格的每一行、每一列都没有重复数字。',
    '黑格不能上下或左右相邻；允许对角相邻。',
    '所有白格必须通过上下左右相邻的白格连成一个整体。',
)
NATIVE_FULL = {
    'nonogram': (
        '按左侧与上方的数字涂黑方格；数字依次表示连续黑格的长度。',
        '同行或同列的相邻黑格段之间，至少留一个白格。',
        '行线索从左到右读，列线索从上到下读。线索0表示整行或整列留白。',
        '可用小叉标记确定留白的格子；小叉是笔记，不是线索。',
    ),
    'maze': (
        '从标注“入口”的外墙缺口进入，沿通道画线，到标注“出口”的缺口离开。',
        '只能上下左右通行，不能穿过墙线，也不能斜穿墙角。',
        '无需走遍所有格子。入口为空心圆，出口为双圆，文字与开口同时保留。',
    ),
}


def _native(record):
    puzzle = record.get('puzzle', record)
    if not isinstance(puzzle, dict) or not isinstance(puzzle.get('params'), dict):
        raise ValueError('Native rule record requires puzzle params')
    return puzzle


def _rules(record):
    rules = record.get('rules_zh')
    if (not isinstance(rules, (list, tuple)) or not rules
            or any(not isinstance(rule, str) or not rule.strip() for rule in rules)):
        raise ValueError('Full public rules must be a nonempty sequence of strings')
    return tuple(rules)


def native_rule_key(record):
    """Hashable identity; board dimensions alone do not change the gameplay."""
    puzzle = _native(record)
    kind, params = puzzle['type_id'], puzzle['params']
    fields = {'sudoku': ('size', 'box_rows', 'box_cols'),
              'nonogram': ('colors',), 'maze': ()}.get(kind)
    gameplay = params if fields is None else {key: params.get(key) for key in fields}
    return ('native', kind, puzzle.get('ruleset_version'),
            json.dumps(gameplay, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False))


def extended_rule_key(record):
    """Keep changed rule text distinct; difficulty/geometry params alone are not rules."""
    rules = _rules(record)
    return ('extended', record['type_id'], record.get('ruleset_version'), rules)


def _full_rules(record, extended=False):
    if extended:
        return _rules(record)
    puzzle = _native(record)
    kind = puzzle['type_id']
    if record.get('rules_zh') is not None:
        return _rules(record)
    if kind == 'sudoku':
        params = puzzle['params']; n, rows, cols = (params[key] for key in ('size', 'box_rows', 'box_cols'))
        return (f'在每个空格填入一个1至{n}的数字，保留题面给出的数字。',
                f'每一行、每一列、每个{rows}×{cols}粗线宫内，数字均不能重复。',
                '可在空格里记小字候选数；候选是笔记，不是线索。')
    if kind not in NATIVE_FULL:
        raise ValueError('Unknown native type needs full public rules')
    return NATIVE_FULL[kind]


def rule_text(record, extended=False):
    """Calendar-page summary; unfamiliar extended variants retain all source text."""
    if extended:
        rules = _rules(record)
        if record['type_id'] == 'hitori' and rules == HITORI_RULES:
            return '涂黑部分数字，使白格行列无重复；黑格不共边，白格上下左右连通。'
        return '\n'.join(rules)
    puzzle = _native(record); kind = puzzle['type_id']
    if kind == 'sudoku':
        p = puzzle['params']
        return f'填入1至{p["size"]}：每行、每列、每个{p["box_rows"]}×{p["box_cols"]}粗线宫内数字均不重复。'
    if kind == 'nonogram':
        return '数字依次表示行列连续黑格长度；段间至少留一白格，0表示全白。'
    if kind == 'maze':
        return '从入口沿通道到出口，不穿墙，不斜走；无需走遍所有格。'
    return '\n'.join(_full_rules(record))


def rule_hint(record, extended=False):
    """A labelled reminder, never a replacement for the first or full rules."""
    if extended:
        if record['type_id'] == 'hitori' and _rules(record) == HITORI_RULES:
            return '提示：涂黑一些数字，让白格中的每行、每列都没有重复数字。'
        return ''
    return {'sudoku': '提示：在空格中填数字，行、列和粗线框出的区域都不能重复。',
            'nonogram': '提示：按行、列旁的数字涂黑方格。',
            'maze': '提示：从入口沿通道走到出口，不能穿过墙线。'}.get(_native(record)['type_id'], '')


def _lines(text, font, width, size):
    from reportlab.pdfbase import pdfmetrics
    result, line = [], ''
    for char in text:
        if char == '\n':
            result.append(line); line = ''; continue
        if pdfmetrics.stringWidth(line + char, font, size) / MM <= width:
            line += char; continue
        if not line:
            raise ValueError('Guide glyph exceeds available width')
        if char in '，。；：！？、）】》〉」』”’％%' and len(line) > 2:
            result.append(line[:-2]); line = line[-2:] + char
        elif line[-1] in '（【《〈「『“‘' and len(line) > 1:
            result.append(line[:-1]); line = line[-1] + char
        else:
            result.append(line); line = char
    if line:
        result.append(line)
    # Rebalance a tiny trailing fragment while preserving the complete rule.
    if len(result)>1 and len(result[-1])<=4 and len(result[-2])>8:
        cut=len(result[-2])-4
        while cut>0 and result[-2][cut-1] in '0123456789.–—−+-/':
            cut-=1
        tail=result[-2][cut:]+result[-1]
        if pdfmetrics.stringWidth(tail,font,size)/MM<=width:
            result[-2]=result[-2][:cut]
            result[-1]=tail
    return result


def write_rule_guide(records, destination, dimensions, font, extended=False, *, top_margin_mm=12):
    """Write a separate, paginated full-rule guide and return its measured pages.

    ``font`` accepts an already registered Publisher font or an embeddable font
    path. ``dimensions`` is (width_mm, height_mm). Existing files are preserved.
    The report contains only public rule names/text and physical page geometry.
    """
    if not isinstance(records, (list, tuple)) or not records:
        raise ValueError('Guide requires public rule records')
    if (not isinstance(dimensions, (list, tuple)) or len(dimensions) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in dimensions)):
        raise ValueError('Guide dimensions must be two finite numbers')
    width, height = dimensions
    if type(top_margin_mm) not in (int,float) or not math.isfinite(top_margin_mm) or not 12<=top_margin_mm<=30:
        raise ValueError('Guide top margin must be between 12 and 30 mm')
    if width < 60 or height < 70:
        raise ValueError('Guide paper is too small for 12 mm margins and 11 pt text')
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise ValueError('Rule guide destination already exists')
    entries, seen = [], set()
    key_function = extended_rule_key if extended else native_rule_key
    for record in records:
        key = key_function(record)
        if key in seen:
            continue
        seen.add(key)
        kind = record['type_id'] if extended else _native(record)['type_id']
        name = record.get('name_zh') or NAMES.get(kind, kind)
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Rule guide name must be text')
        entries.append({'type_id': kind, 'name_zh': name, 'rule_key': key,
                        'rules_zh': list(_full_rules(record, extended))})
    from render_calendar import publisher_path
    import sys
    runtime = str(publisher_path() / 'runtime')
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    from puzzle_publisher.render import _Page, _font
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen.canvas import Canvas
    if font not in pdfmetrics.getRegisteredFontNames():
        font = _font(font)[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.rule-guide-', suffix='.pdf', dir=target.parent, delete=False) as temp:
        scratch = Path(temp.name)
    try:
        cv = Canvas(str(scratch), pagesize=(width * MM, height * MM), invariant=1,
                    initialFontName=font, initialFontSize=11)
        cv.setTitle('解谜规则手册'); cv.setAuthor('Puzzle Calendar')
        reports, page, y = [], None, 0
        line_height = (pdfmetrics.getAscentDescent(font, 11)[0] - pdfmetrics.getAscentDescent(font, 11)[1]) / MM
        heading_height = (pdfmetrics.getAscentDescent(font, 15)[0] - pdfmetrics.getAscentDescent(font, 15)[1]) / MM
        body_width, bottom = width - 26, height - 25

        def new_page():
            nonlocal page, y
            if page is not None:
                reports.append(page.finish())
            number = len(reports) + 1
            page = _Page(cv, font, width, height, [12, top_margin_mm, width - 12, height - 12], 'rule_guide', number)
            page.text('解谜规则', 13, top_margin_mm+.5, 18, bold=True, role='guide_title')
            page.record['rule_entries'] = []
            y = top_margin_mm+15

        def heading(entry, index, continued=False):
            nonlocal y
            title = f'{index + 1:02d}  {entry["name_zh"]}' + ('（续）' if continued else '')
            title_lines = _lines(title, font, body_width - .2, 15)
            required = len(title_lines) * (heading_height + 1.5) + 2 + line_height
            if required > bottom - (top_margin_mm+15):
                raise ValueError('Rule heading cannot fit at readable size')
            if page is None or y + required > bottom:
                new_page()
            page.record['rule_entries'].append({'type_id': entry['type_id'], 'rule_key': entry['rule_key'],
                                                'name_zh': entry['name_zh'], 'continued': continued})
            for line in title_lines:
                page.text(line, 13, y, 15, bold=True, role='rule_name')
                y += heading_height + 1.5
            y += 2

        for index, entry in enumerate(entries):
            heading(entry, index)
            for paragraph in entry['rules_zh']:
                for line in _lines(paragraph, font, body_width, 11):
                    if y + line_height > bottom:
                        new_page(); heading(entry, index, continued=True)
                    if line:
                        page.text(line, 13, y, 11, role='rule_text')
                    y += line_height + 1.5
                # The last line already contributes 1.5 mm leading: add the
                # remaining 3.5 mm to make a 5 mm gap between paragraphs.
                y += 3.5
            y += 5
        reports.append(page.finish()); cv.save()
        scratch.rename(target)
        return {'pages': reports, 'rule_count': len(entries),
                'rules': entries, 'font_pt': 11, 'margin_mm': 12,'top_margin_mm':top_margin_mm}
    finally:
        scratch.unlink(missing_ok=True)
