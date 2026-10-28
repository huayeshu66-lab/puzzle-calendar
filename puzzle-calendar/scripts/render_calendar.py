#!/usr/bin/env python3
"""Thin calendar PDF renderer; imports the installed Publisher without modifying it."""
from __future__ import annotations

import argparse
import calendar
import copy
import datetime as dt
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

VERSION = '0.7.0'
MM = 72 / 25.4
WEEKDAYS = '一二三四五六日'


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: '+key)
            result[key] = value
        return result
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Input JSON exceeds 32 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def publisher_path(value=None):
    candidates = [Path(value).expanduser()] if value else [
        Path(__file__).resolve().parents[2] / 'puzzle-publisher',
        Path.home() / '.codex/skills/puzzle-publisher']
    for candidate in candidates:
        if (candidate/'runtime/puzzle_engine/api.py').is_file():
            return candidate.resolve()
    raise ValueError('Installed puzzle-publisher runtime not found; use --publisher-dir')


def proved(report):
    if not isinstance(report, dict) or str(report.get('status')).lower() != 'unique' or report.get('proof_complete') is not True:
        return False
    if report.get('proof_method') == 'enumeration':
        return report.get('search_complete') is True
    checks = report.get('proof_checks')
    return (report.get('proof_method') == 'tree' and report.get('search_complete') is None
            and isinstance(checks, dict) and bool(checks) and all(v is True for v in checks.values()))


def validate_inputs(document, records):
    from puzzle_engine.api import canonical_hash, solve_puzzle, validate_answer
    request, plan = document['request'], document['plan']
    form = request['calendar_form']
    if form not in ('daily', 'weekly', 'monthly'):
        raise ValueError('Unsupported calendar_form')
    firstweekday = request.get('week_start', 0)
    if type(firstweekday) is not int or firstweekday not in (0, 6):
        raise ValueError('week_start must be 0 or 6')
    start, end = [dt.date.fromisoformat(request['date_range'][key]) for key in ('start', 'end')]
    if start > end:
        raise ValueError('Invalid date range')
    slots, pages = plan['slots'], plan['pages']
    if not slots or not pages or not isinstance(records, list):
        raise ValueError('Nonempty plan and records list required')
    slotmap, owners, pageids = {}, [], set()
    for slot in slots:
        ident = slot['slot_id']
        if ident in slotmap or type(slot.get('puzzles')) is not int or slot['puzzles'] != 1:
            raise ValueError('Unsupported or duplicate slot: baseline requires exactly one puzzle per slot')
        date = dt.date.fromisoformat(slot['date'])
        if not start <= date <= end or slot['weekday'] != date.weekday():
            raise ValueError('Slot date or weekday is inconsistent')
        slotmap[ident] = slot
    for page in pages:
        if page['page_id'] in pageids or len(page['slot_ids']) != 1:
            raise ValueError('Unsupported page: baseline requires exactly one slot per page')
        pageids.add(page['page_id']); owners.extend(page['slot_ids'])
        if page['slot_ids'][0] not in slotmap:
            raise ValueError('Page references missing slot')
        slot = slotmap[page['slot_ids'][0]]
        event = dt.date.fromisoformat(slot['date'])
        if form == 'monthly':
            expected = list(calendar.Calendar(firstweekday).itermonthdates(event.year, event.month))
            unit = event.strftime('%Y-%m')
        elif form == 'weekly':
            first = event-dt.timedelta(days=(event.weekday()-firstweekday) % 7)
            expected = [first+dt.timedelta(days=i) for i in range(7)]; unit = first.isoformat()
        else:
            expected, unit = [event], event.isoformat()
        if slot['unit_key'] != unit or page['unit_key'] != unit:
            raise ValueError('Date unit differs from owning slot')
        display = page['display_dates']
        if [item['date'] for item in display] != [d.isoformat() for d in expected]:
            raise ValueError('Calendar display dates differ from actual calendar')
        for item, date in zip(display, expected):
            in_unit = date.month == event.month if form == 'monthly' else True
            if (item['weekday'] != date.weekday() or item['in_unit'] is not in_unit
                    or item['in_range'] is not (start <= date <= end)):
                raise ValueError('Calendar weekday/range flags differ from actual dates')
        rows = len(expected)//7 if form == 'monthly' else 1
        if page['row_count'] != rows or slot['date'] not in page['dates']:
            raise ValueError('Calendar row count or event ownership differs')
    if len(owners) != len(set(owners)) or set(owners) != set(slotmap):
        raise ValueError('Every requested slot must belong to exactly one page')
    indexed, ids, seen = {}, set(), set()
    for record in records:
        ident, pid = record['slot_id'], record['puzzle_id']
        if ident in indexed or ident not in slotmap or pid in ids:
            raise ValueError('Missing, duplicate or extra record mapping')
        if not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}', pid):
            raise ValueError('Invalid puzzle_id')
        if record['puzzle'].get('puzzle_id', pid) != pid or not proved(record['validation']):
            raise ValueError('Puzzle ID or saved uniqueness evidence invalid')
        puzzle = {key: copy.deepcopy(record['puzzle'][key]) for key in ('type_id','ruleset_version','params','clues')}
        fresh = solve_puzzle(puzzle)
        check = validate_answer(puzzle, record['solution'])
        if not proved(fresh) or not check['valid'] or fresh['solutions'][0] != record['solution']:
            raise ValueError('Fresh uniqueness or independent solution verification failed')
        digest = canonical_hash(puzzle)
        if digest != record['canonical_hash'] or digest in seen:
            raise ValueError('Canonical hash mismatch or repeated puzzle')
        seen.add(digest); ids.add(pid)
        indexed[ident] = {'slot_id':ident, 'puzzle_id':pid, 'puzzle':puzzle,
                          'difficulty':copy.deepcopy(record.get('difficulty', {}))}
    if set(indexed) != set(slotmap):
        raise ValueError('Every requested slot needs exactly one record')
    return request, pages, indexed


def select_plan(document, page_ids, instructions, first_rules_slots):
    from calendar_plan import plan_calendar
    if document.get('spec_version') != '1.0' or document['plan'] != plan_calendar(document['request'])['plan']:
        raise ValueError('Full plan differs from freshly derived calendar plan')
    result = copy.deepcopy(document)
    pages = result['plan']['pages']; all_slots = {s['slot_id'] for s in result['plan']['slots']}
    selected = page_ids.split(',') if isinstance(page_ids, str) else page_ids
    if selected is not None:
        if not selected or len(selected) != len(set(selected)) or not set(selected) <= {p['page_id'] for p in pages}:
            raise ValueError('page_ids must name distinct existing pages')
        indexes = [i for i,p in enumerate(pages) if p['page_id'] in selected]
        if instructions == 'first_occurrence' and indexes != list(range(len(indexes))) and first_rules_slots is None:
            raise ValueError('Later samples need explicit first_rules_slots from full type assignment')
        pages = [p for p in pages if p['page_id'] in selected]
        slots = {s for p in pages for s in p['slot_ids']}
        result['plan']['pages'] = pages
        result['plan']['slots'] = [s for s in result['plan']['slots'] if s['slot_id'] in slots]
    if first_rules_slots is not None and (not isinstance(first_rules_slots,list)
            or len(first_rules_slots) != len(set(first_rules_slots)) or not set(first_rules_slots) <= all_slots):
        raise ValueError('first_rules_slots must be distinct IDs from full plan')
    return result


def header(page, entry, form, theme, print_mode, appearance=None):
    from puzzle_publisher.render import colors
    left, _, right, _ = page.safe
    color = colors.HexColor('#315a68') if print_mode == 'color' else colors.black
    if form == 'daily':
        from page_design import daily_header
        return daily_header(page, entry, color, appearance, print_mode)
    if theme == 'newspaper':
        page.line(left+1, 20, right-1, 20, 1.2, color)
        page.line(left+1, 21.5, right-1, 21.5, .6, color)
    elif theme == 'chinese':
        page.rect(left+.5, 12.5, right-left-1, 11, .7, color=color)
    elif theme == 'modern':
        page.line(left+.7, 13, left+.7, 34, 2, color)
        page.line(left+1, 36, right-1, 36, .7, color)
    if form == 'monthly':
        year, month = entry['unit_key'].split('-')
        page.text(f'{year} / {month}', left+2, 26, 20, role='calendar_date')
        display = entry['display_dates']; rows = entry['row_count']
        cell = (right-left-2)/7; top, pitch = 40, 7.5
        for col in range(7):
            day = display[col]['weekday']
            page.text(WEEKDAYS[day], left+1+(col+.5)*cell, top, 11, align='center', role='weekday')
        top += 7
        for index, item in enumerate(display):
            if not item['in_unit']:
                continue
            row, col = divmod(index, 7)
            date = dt.date.fromisoformat(item['date'])
            page.text(str(date.day),left+1+(col+.5)*cell,top+row*pitch,12,
                      align='center',role='month_day')
        finish = top+rows*pitch
        page.line(left+1, finish, right-1, finish, .6)
        return finish+5
    if form == 'weekly':
        display = entry['display_dates']
        page.text(f'{display[0]["date"]} 至 {display[-1]["date"]}',left+2,26,14,role='calendar_date')
        cell = (right-left-2)/7
        for col, item in enumerate(display):
            center = left+1+(col+.5)*cell
            page.text(WEEKDAYS[item['weekday']],center,39,11,align='center',role='weekday')
            date = dt.date.fromisoformat(item['date'])
            page.text(f'{date.month}/{date.day}',center,46,12,align='center',role='week_day')
        page.line(left+1,55,right-1,55,.6)
        return 60
    date = dt.date.fromisoformat(entry['unit_key'])
    page.text(f'{date.isoformat()}  星期{WEEKDAYS[date.weekday()]}',left+2,26,18,role='calendar_date')
    if theme != 'modern':
        page.line(left+1,38,right-1,38,.6,color)
    return 43


def draw_pages(request, entries, public, destination, options, font, *, solutions=None,
               information_by_page=None, information_tops=None):
    from reportlab.pdfgen.canvas import Canvas
    from puzzle_publisher.render import _Page, _geometry, _grid, _maze, NAMES
    from page_design import rule_lane, puzzle_caption, draw_footer, editorial_caption
    from rule_notes import native_rule_key
    width, height = options['dimensions']; theme = options['theme']
    canvas = Canvas(str(destination),pagesize=(width*MM,height*MM),invariant=1,
                    pageCompression=1,initialFontName=font,initialFontSize=11)
    appearance = options['appearance']
    canvas.setTitle((appearance['book_title']+' · 答案' if appearance['book_title'] else '答案')
                    if solutions is not None else appearance['book_title'])
    canvas.setAuthor('Puzzle Calendar'); reports, seen_rules = [], set()
    for number, entry in enumerate(entries,1):
        record = public[entry['slot_ids'][0]]; puzzle = record['puzzle']; pid = record['puzzle_id']
        page = _Page(canvas,font,width,height,[12,12,width-12,height-12],
                     'answer' if solutions is not None else 'puzzle',number)
        if appearance['layout']=='editorial':
            from calendar_styles import configure_page
            configure_page(page,appearance)
        y = header(page,entry,request['calendar_form'],theme,options['print_mode'],appearance)
        key = native_rule_key(record)
        first = key not in seen_rules if options.get('first_rules_slots') is None else record['slot_id'] in options['first_rules_slots']
        full = (options['instructions']=='every_puzzle' or
                options['instructions']=='first_occurrence' and first)
        show = solutions is None and full
        seen_rules.add(key)
        modules = (information_by_page or {}).get(entry['page_id'], [])
        editorial=appearance['layout']=='editorial'
        if modules:
            from page_information import draw_information
            page.record['information'] = [
                {key: module[key] for key in ('module_id','kind','classification')}
                for module in modules]
            if not editorial:
                y = max(y, (information_tops or {}).get(entry['page_id'], y))
                page.record['information_top_mm'] = y
                y = draw_information(page, modules, y, width-26, font_size=11,
                                     show_titles=appearance['show_information_titles'])
        title=NAMES[puzzle['type_id']]+(' · 答案' if solutions is not None else '')
        if editorial:
            from page_design import editorial_board_bottom
            bottom=editorial_board_bottom(height,appearance)
        else:
            y = puzzle_caption(page,title,record,y,
                               hint=appearance['show_rule_hint'] and not full and options['instructions']!='none')
            bottom = rule_lane(page,record,full,answer=solutions is not None)
        editing_font=page.font
        page.font=font  # Keep the native board's clue typography and geometry frozen.
        geometry = _geometry(page,puzzle,y,bottom,False)
        solution = solutions[record['slot_id']] if solutions is not None else None
        if puzzle['type_id'] == 'maze':
            _maze(page,puzzle,geometry,solution,False)
        else:
            _grid(page,puzzle,geometry,solution)
        page.font=editing_font
        if editorial:
            editorial_caption(page,title,geometry['component_bbox_mm'][3],modules,appearance)
        draw_footer(page,appearance,pid,number,len(entries))
        page.record.update(page_id=entry['page_id'],slot_id=record['slot_id'],puzzle_id=pid,
                           instructions_shown=show,calendar_rows=entry['row_count'],geometry=geometry)
        reports.append(page.finish())
    canvas.save()
    return {'page_count':len(reports),'pages':reports,'dimensions_mm':[width,height]}


def calibration(destination, dimensions, font):
    from reportlab.pdfgen.canvas import Canvas
    from puzzle_publisher.render import _Page
    width,height = dimensions
    canvas = Canvas(str(destination),pagesize=(width*MM,height*MM),invariant=1,
                    initialFontName=font,initialFontSize=11)
    page = _Page(canvas,font,width,height,[12,12,width-12,height-12],'calibration',1)
    page.text('打印校准 · 使用实际大小100%',14,17,15)
    page.text('下方横线打印后应为100毫米。',14,32,11)
    page.line(20,50,120,50,.6)
    page.line(20,48,20,52,.6); page.line(120,48,120,52,.6)
    page.text('请测量长度，并试写与检查格线。',14,60,11)
    report = page.finish(); canvas.save()
    return {'page_count':1,'pages':[report],'dimensions_mm':[width,height],
            'ruler_mm':100,'physical_measurement':'pending'}


def calendar_tokens(entry, form, layout='classic'):
    if form=='daily':
        date = dt.date.fromisoformat(entry['unit_key'])
        if layout=='editorial':
            return [str(date.year),f'{date.month}月',f'{date.day:02d}','星期'+WEEKDAYS[date.weekday()]]
        return [date.isoformat(),'星期'+WEEKDAYS[date.weekday()]]
    if form=='weekly':
        return [entry['display_dates'][0]['date'],entry['display_dates'][-1]['date']]
    year,month = entry['unit_key'].split('-')
    return [f'{year} / {month}']


def _vertical_weekday_present(page,expected):
    """Check actual upright glyph order/spacing in the date zone, never hidden text."""
    if not re.fullmatch(r'星期[一二三四五六日]',expected):return False
    runs=[];height=float(page.mediabox.height)/MM;width=float(page.mediabox.width)/MM
    def visit(text,cm,tm,font,size):
        value=text.strip()
        if len(value)!=1 or value not in expected:return
        x=(tm[4]*cm[0]+tm[5]*cm[2]+cm[4])/MM
        y=height-(tm[4]*cm[1]+tm[5]*cm[3]+cm[5])/MM
        if 20<=y<=63 and 12<=x<=width-12:runs.append((value,x,y))
    page.extract_text(visitor_text=visit)
    for a in runs:
        for b in runs:
            for c in runs:
                if a[0]+b[0]+c[0]!=expected:continue
                if max(a[1],b[1],c[1])-min(a[1],b[1],c[1])>.1:continue
                if 4<=b[2]-a[2]<=7 and abs((b[2]-a[2])-(c[2]-b[2]))<.1:return True
    return False


def inspect_pdf(path, dimensions, ids=None, ruler=False, *, dates=None):
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
    reader = PdfReader(path)
    if reader.is_encrypted or reader.attachments or reader.get_fields():
        raise ValueError('Unexpected PDF encryption, attachments or form')
    expected = len(dates) if dates is not None else len(ids) if ids is not None else 1
    if ids is not None and dates is not None and len(ids)!=len(dates):
        raise ValueError('Date and puzzle ID mapping counts differ')
    if len(reader.pages) != expected:
        raise ValueError('PDF page count differs from plan')
    def embedded(reference):
        font = reference.get_object()
        if font.get('/DescendantFonts'):
            return all(embedded(child) for child in font['/DescendantFonts'])
        descriptor = font.get('/FontDescriptor')
        return descriptor and any(k in descriptor.get_object() for k in ('/FontFile','/FontFile2','/FontFile3'))
    for number,page in enumerate(reader.pages):
        actual = [float(page.mediabox.width)/MM,float(page.mediabox.height)/MM]
        if any(abs(a-b)>.01 for a,b in zip(actual,dimensions)) or page.get('/Rotate',0)!=0:
            raise ValueError('PDF physical dimensions or rotation differ')
        if not all(embedded(font) for font in page['/Resources']['/Font'].values()):
            raise ValueError('PDF contains unembedded font')
        if ids is not None and ids[number] is not None and page.extract_text().split().count(ids[number]) != 1:
            raise ValueError('Actual PDF puzzle ID differs from page mapping')
        if dates is not None:
            tokens=dates[number]
            if not isinstance(tokens,list) or not tokens or any(not isinstance(t,str) or not t.strip() for t in tokens):
                raise ValueError('Calendar date check needs nonempty per-page text tokens')
            actual_text=' '.join(page.extract_text().split())
            if any(' '.join(token.split()) not in actual_text and not _vertical_weekday_present(page,token) for token in tokens):
                raise ValueError('Actual PDF calendar date differs from page mapping')
    if ruler:
        previous, found = None, False
        for args,op in ContentStream(reader.pages[0].get_contents(),reader).operations:
            if op == b'm': previous = tuple(map(float,args))
            elif op == b'l' and previous:
                end = tuple(map(float,args))
                found |= abs(end[1]-previous[1])<.001 and abs(abs(end[0]-previous[0])/MM-100)<.001
                previous = end
        if not found:
            raise ValueError('Actual PDF 100 mm calibration line missing')
    return {'page_count':len(reader.pages),'fonts_embedded':True,'page_size_checked':True,
            'puzzle_ids_checked':ids is not None and all(ident is not None for ident in ids),
            'calendar_dates_checked':dates is not None,'ruler_checked':ruler}


def render_calendar(document, records, output_dir, *, publisher_dir=None, font=None,
                    theme='minimal', paper='A5', orientation='portrait', print_mode='bw',
                    instructions='first_occurrence', page_ids=None, first_rules_slots=None,
                    information=None, appearance=None):
    """Render supplied public information with caller-declared provenance.

    The information contract validates labels, ownership, and provenance
    fields; it does not independently establish the truth of supplied facts.
    """
    dependency = publisher_path(publisher_dir)
    sys.path.insert(0,str(dependency/'runtime'))
    from puzzle_publisher.render import _font
    from puzzle_publisher import __version__ as publisher_version
    from page_design import normalize_appearance,validate_layout
    appearance = normalize_appearance(appearance)
    if orientation not in ('portrait','landscape') or paper not in ('A4','A5'):
        raise ValueError('Unsupported paper or orientation')
    source_plan = document
    information_by_page = {}
    if information is not None:
        from page_information import prepare_information
        information_by_page = prepare_information(source_plan, information)
    document = select_plan(document,page_ids,instructions,first_rules_slots)
    if isinstance(records,dict):
        if records.get('state') != 'complete' and not (page_ids is not None and records.get('state')=='incomplete'):
            raise ValueError('Full rendering requires complete content envelope')
        records = records['records']
    request, entries, public = validate_inputs(document, records)
    validate_layout(appearance,request,instructions,orientation)
    dimensions = {'A4':(210,297),'A5':(148,210)}[paper]
    if orientation == 'landscape': dimensions = dimensions[::-1]
    if theme not in ('minimal','newspaper','chinese','modern') or print_mode not in ('bw','color'):
        raise ValueError('Unsupported theme or print mode')
    if instructions not in ('reference','first_occurrence','every_puzzle','none'):
        raise ValueError('Unsupported instructions policy')
    registered, fontpath, fonthash = _font(font)
    options = dict(dimensions=dimensions,theme=theme,print_mode=print_mode,instructions=instructions,
                   first_rules_slots=first_rules_slots,appearance=appearance)
    destination = Path(output_dir).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Output directory already exists; choose a new path')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.calendar-',dir=destination.parent))
    try:
        student = draw_pages(request,entries,public,stage/'publication.pdf',options,registered,
                             information_by_page=information_by_page)
        solutions = {row['slot_id']:row['solution'] for row in records}
        information_tops = {page['page_id']:page['information_top_mm'] for page in student['pages']
                            if 'information_top_mm' in page}
        answers = draw_pages(request,entries,public,stage/'answers.pdf',options,registered,solutions=solutions,
                             information_by_page=information_by_page, information_tops=information_tops)
        ruler = calibration(stage/'calibration.pdf',dimensions,registered)
        guide = None
        if instructions == 'reference':
            from rule_notes import write_rule_guide
            guide = write_rule_guide([public[e['slot_ids'][0]] for e in entries],
                                    stage/'guide.pdf',dimensions,registered,
                                    top_margin_mm=20 if appearance['style_id']=='cyber-noir' else 12)
        ids = [public[entry['slot_ids'][0]]['puzzle_id'] for entry in entries]
        date_checks = [calendar_tokens(e,request['calendar_form'],appearance['layout']) for e in entries]
        checks = {name:inspect_pdf(stage/name,dimensions,
                                   ids if name!='calibration.pdf' and appearance['show_puzzle_id'] else None,
                                   ruler=name=='calibration.pdf',dates=date_checks if name!='calibration.pdf' else None)
                  for name in ('publication.pdf','answers.pdf','calibration.pdf')}
        if guide is not None:
            # Guide pages contain public rules, without the puzzle ID mapping.
            checks['guide.pdf'] = inspect_pdf(stage/'guide.pdf',dimensions,
                                              [None]*len(guide['pages']))
        report = {'renderer_version':VERSION,'student':student,'answers':answers,'calibration':ruler,
                  'actual_pdf_checks':checks,'visual_qa':'pending',
                  'content_semantics':'fresh solve and direct rule check; visual comparison pending'}
        if guide is not None: report['guide'] = guide
        (stage/'layout-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        manifest = {'renderer_version':VERSION,'publisher_version':publisher_version,
                    'publisher_dir':str(dependency),'private_render_api_dependency':True,
                    'status':'rendered_pending_visual_review','visual_qa':'pending',
                    'physical_print_test':'pending','difficulty_calibration':'pending','production_ready':False,
                    'representative_subset':page_ids is not None,
                    'full_plan_pages':len(source_plan['plan']['pages']),
                    'rules_first_positions':'explicit_full_assignment' if first_rules_slots is not None else 'derived_from_rendered_prefix',
                    'font':{'path':str(fontpath),'sha256':fonthash,'embedded':True},
                    'options':options,'page_count':len(entries),
                    'page_map':[{'page_id':e['page_id'],'slot_id':e['slot_ids'][0],
                                 'puzzle_id':public[e['slot_ids'][0]]['puzzle_id']} for e in entries],
                    'files':[{'name':name,'sha256':sha256((stage/name).read_bytes()).hexdigest(),
                              'bytes':(stage/name).stat().st_size,
                              'role':'private_answers' if name=='answers.pdf' else 'public_or_metadata'}
                             for name in ('publication.pdf','answers.pdf','calibration.pdf','layout-report.json')]}
        if guide is not None:
            manifest['files'].append({'name':'guide.pdf','sha256':sha256((stage/'guide.pdf').read_bytes()).hexdigest(),
                                      'bytes':(stage/'guide.pdf').stat().st_size,'role':'public_rules'})
        if information is not None:
            payload_bytes = json.dumps(information,sort_keys=True,ensure_ascii=False,
                                       separators=(',',':'),allow_nan=False).encode('utf-8')
            modules = []
            for page_id, rows in information_by_page.items():
                for row in rows:
                    item = {key:row[key] for key in ('module_id','kind','classification')}
                    item['page_id'] = page_id
                    if 'provenance' in row:
                        item['provenance'] = {key:row['provenance'][key] for key in ('origin','status','source','method')
                                              if key in row['provenance']}
                    modules.append(item)
            manifest['information'] = {
                'payload_sha256':sha256(payload_bytes).hexdigest(),
                'hash_method':'sha256_canonical_json','modules':modules,
                'truth_verification':'caller_supplied_provenance_contract_not_fact_check'}
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        destination.mkdir()  # Reserve exclusive ownership immediately before publishing files.
        try:
            for item in stage.iterdir(): item.rename(destination/item.name)
        except BaseException:
            shutil.rmtree(destination); raise
        return {'output_dir':str(destination),'manifest':str(destination/'manifest.json'),
                'status':manifest['status'],'pages':len(entries)}
    finally:
        shutil.rmtree(stage,ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan','records','output-dir'): parser.add_argument('--'+name,required=True)
    parser.add_argument('--publisher-dir'); parser.add_argument('--font')
    parser.add_argument('--page-ids',help='Comma-separated exact page IDs from the unchanged full plan')
    parser.add_argument('--first-rules-slots',help='JSON array of first-rule slot IDs from full type assignment')
    parser.add_argument('--information',help='JSON public information payload; supplied provenance is not independent fact verification')
    parser.add_argument('--appearance',help='JSON page appearance and optional footer; default omits titles, hints and internal identifiers')
    parser.add_argument('--theme',choices=['minimal','newspaper','chinese','modern'],default='minimal')
    parser.add_argument('--paper',choices=['A4','A5'],default='A5')
    parser.add_argument('--orientation',choices=['portrait','landscape'],default='portrait')
    parser.add_argument('--print-mode',choices=['bw','color'],default='bw')
    parser.add_argument('--instructions',choices=['reference','first_occurrence','every_puzzle','none'],default='first_occurrence')
    args = vars(parser.parse_args(argv)); plan, records = args.pop('plan'), args.pop('records')
    try:
        if args['first_rules_slots'] is not None:
            args['first_rules_slots'] = read_json(args['first_rules_slots'])
        if args['information'] is not None:
            args['information'] = read_json(args['information'])
        if args['appearance'] is not None:
            args['appearance'] = read_json(args['appearance'])
        result = render_calendar(read_json(plan),read_json(records),**args)
        print(json.dumps(result,ensure_ascii=False)); return 0
    except (ValueError,KeyError,TypeError,OSError,ImportError) as error:
        print(json.dumps({'error':str(error),'error_type':type(error).__name__},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
