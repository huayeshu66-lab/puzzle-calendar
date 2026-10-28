"""Measured typography and bottom rule lanes shared by both PDF renderers."""
from hashlib import sha256
from pathlib import Path
import copy
import math
import unicodedata
import re

MM = 72 / 25.4


def normalize_appearance(value=None):
    """Public page choices, separate from content identity and book metadata."""
    from calendar_styles import get_style
    defaults = {'book_title':'','show_information_titles':False,
                'show_rule_hint':False,'show_puzzle_id':False,
                'show_page_number':False,'footer':None,'layout':'classic',
                'accent_color':None,'style_id':'warm-editorial','serif_font_path':None}
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(defaults):
        raise ValueError('Unknown or malformed appearance settings')
    result = {**defaults,**copy.deepcopy(value)}
    preset=get_style(result['style_id'])
    if 'accent_color' not in value:result['accent_color']=preset['accent_color']
    if result['serif_font_path'] is not None:
        p=Path(result['serif_font_path']) if isinstance(result['serif_font_path'],str) else None
        if p is None or not p.is_absolute() or not p.is_file() or p.suffix.lower() not in ('.ttf','.ttc'):
            raise ValueError('serif_font_path requires an existing absolute TTF/TTC path')
    if result['layout'] not in ('classic','editorial'):
        raise ValueError('layout must be classic or editorial')
    if not isinstance(result['accent_color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',result['accent_color']):
        raise ValueError('accent_color requires #RRGGBB')
    for key in ('show_information_titles','show_rule_hint','show_puzzle_id','show_page_number'):
        if type(result[key]) is not bool:
            raise ValueError(key+' must be boolean')
    def text(value, name):
        if (not isinstance(value,str) or not value.strip() or len(value)>80
                or any(unicodedata.category(c) in ('Cc','Cf','Cs') for c in value)):
            raise ValueError(name+' must be nonempty printable text of at most 80 characters')
    if result['book_title']!='':
        text(result['book_title'],'book_title')
    footer = result['footer']
    if footer is not None:
        if not isinstance(footer,dict):
            raise ValueError('footer must be null or a text/logo object')
        if set(footer)=={'text'}:
            text(footer['text'],'footer.text')
        elif set(footer)=={'logo','width_mm','height_mm'}:
            path = Path(footer['logo']) if isinstance(footer['logo'],str) else None
            if path is None or not path.is_absolute() or not path.is_file() or path.stat().st_size>10*1024*1024:
                raise ValueError('footer.logo requires an existing absolute image path of at most 10 MiB')
            for key in ('width_mm','height_mm'):
                if type(footer[key]) not in (int,float) or not math.isfinite(footer[key]) or footer[key]<=0:
                    raise ValueError('footer logo dimensions must be finite and positive')
            if footer['height_mm']>8:
                raise ValueError('footer logo height must not exceed 8 mm')
            from PIL import Image
            with Image.open(path) as image:
                if image.format not in ('PNG','JPEG') or image.width*image.height>20_000_000:
                    raise ValueError('footer.logo must be a PNG/JPEG with at most 20 million pixels')
                image.verify()
        else:
            raise ValueError('footer requires text or logo/width_mm/height_mm, never both')
    return result


def validate_layout(appearance, request, instructions, orientation='portrait'):
    if appearance['layout']=='classic' and appearance['style_id']!='warm-editorial':
        raise ValueError('Nondefault style_id requires editorial layout')
    if appearance['layout']=='editorial' and (request['calendar_form']!='daily'
            or instructions not in ('reference','none') or orientation!='portrait'
            or appearance['show_rule_hint']):
        raise ValueError('editorial requires portrait daily pages, reference/none and no inline rule hint')


def display_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    path = Path(__file__).resolve().parents[1] / 'assets/WorkSans-Bold.ttf'
    name = 'CalendarWorkSansBold'
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    return name, {'name': name, 'path': str(path),
                  'sha256': sha256(path.read_bytes()).hexdigest(), 'embedded': True,
                  'license': 'SIL Open Font License 1.1'}


def daily_header(page, entry, color, appearance=None, print_mode='bw'):
    import datetime as dt
    date = dt.date.fromisoformat(entry['unit_key'])
    left, _, right, _ = page.safe
    appearance = normalize_appearance(appearance)
    if appearance['layout']=='editorial':
        from calendar_styles import draw_header
        return draw_header(page,entry,appearance,print_mode)
    font, metadata = display_font()
    original = page.font
    try:
        page.font = font
        page.text(f'{date.day:02d}', left+20, 14, 56, role='calendar_day')
    finally:
        page.font = original
    page.record['display_font'] = metadata
    # Align real text baselines; font bounding boxes include different descenders.
    from reportlab.pdfbase import pdfmetrics
    day_ascent = pdfmetrics.getAscentDescent(font,56)[0]
    month_ascent = pdfmetrics.getAscentDescent(page.font,18)[0]
    page.text(f'{date.month}月',left+1,14+(day_ascent-month_ascent)/MM,18,role='calendar_month')
    page.text(date.isoformat(), right-1, 15, 10, align='right', role='calendar_date')
    page.text('星期'+'一二三四五六日'[date.weekday()], right-1, 25, 14,
              align='right', role='weekday')
    page.line(left+1, 44, right-1, 44, .6, color)
    return 50


def editorial_caption(page, title, board_bottom, modules, appearance):
    """Quiet caption and selected information below the complete board."""
    from calendar_styles import date_information,vertical_label
    modules=date_information(page,modules,appearance)
    cyber=appearance['style_id']=='cyber-noir'
    name,answer=title.removesuffix(' · 答案'),title.endswith(' · 答案')
    upright=cyber and re.fullmatch(r'[\u3400-\u4dbf\u4e00-\u9fff]{2,5}',name)
    top=board_bottom+5
    if upright:
        label_top=page.height-38
        if board_bottom+3>label_top:raise ValueError('Vertical puzzle label conflicts with the complete board')
        box=vertical_label(page,name,18,label_top,11,4.5,'puzzle_title')
        if box[3]>page.height-14:raise ValueError('Vertical puzzle label exceeds the reserved lane')
        if answer:page.text('答案',14,page.height-45,9.5,role='answer_label')
        end=board_bottom
    else:
        end=top+page.text(title,page.width/2,top,11,align='center',role='puzzle_title')
    if modules:
        from page_information import draw_information
        info_top=page.height-37 if upright else page.height-(34 if cyber else 32)
        if end+5>info_top:
            raise ValueError('editorial board/caption leaves insufficient information space')
        page.record['information_top_mm']=info_top
        start=len(page.texts)
        left=34 if upright else 13
        if upright:page.line(27,page.height-38,27,page.height-15,.6)
        page.record['information_left_mm']=left
        draw_information(page,modules,info_top,page.width-14-left if upright else page.width-26,font_size=11,
                         show_titles=appearance['show_information_titles'],left=left)
        occupied_footer=(appearance['footer'] is not None or appearance['show_puzzle_id']
                         or appearance['show_page_number'])
        limit=page.height-(25 if occupied_footer else 14)
        if any(t['bbox_mm'][3]>limit for t in page.texts[start:]):
            raise ValueError('editorial information exceeds its reserved lane; rewrite or select classic layout')


def editorial_board_bottom(height,appearance):
    """Reserve room for attributed quotations without shrinking the content."""
    return height-(48 if appearance['style_id']=='cyber-noir' else 44)


def draw_footer(page, appearance, puzzle_id, number, total):
    """Keep identifiers in manifests; only print explicitly requested footer items."""
    from reportlab.pdfbase import pdfmetrics
    left,right = 13,page.width-13
    y = page.height-19
    if appearance['show_puzzle_id']:
        page.text(puzzle_id,left,y,9,role='puzzle_id')
        left += pdfmetrics.stringWidth(puzzle_id,page.font,9)/MM+4
    if appearance['show_page_number']:
        label = f'{number} / {total}'
        page.text(label,right,y,9,align='right',role='page_number')
        right -= pdfmetrics.stringWidth(label,page.font,9)/MM+4
    footer = appearance['footer']
    if footer is None:
        return
    center = (left+right)/2
    if 'text' in footer:
        if pdfmetrics.stringWidth(footer['text'],page.font,9)/MM>right-left:
            raise ValueError('footer text does not fit at 9 pt; shorten it')
        page.text(footer['text'],center,y,9,align='center',role='footer_theme')
        page.record['footer'] = {'kind':'text','bbox_mm':page.texts[-1]['bbox_mm']}
    else:
        from reportlab.lib.utils import ImageReader
        w,h = footer['width_mm'],footer['height_mm']
        if w>right-left:
            raise ValueError('footer logo does not fit the available width')
        # Fit into the requested box without stretching or changing aspect ratio.
        data = Path(footer['logo']).read_bytes()
        from io import BytesIO
        image = ImageReader(BytesIO(data)); pw,ph = image.getSize()
        scale = min(w/pw,h/ph); w,h = pw*scale,ph*scale
        box = [center-w/2,page.height-20,center+w/2,page.height-20+h]
        page.bounds(box)
        page.c.drawImage(image,box[0]*MM,(page.height-box[3])*MM,width=w*MM,height=h*MM,mask='auto')
        page.record['footer'] = {'kind':'logo','role':'footer_logo','bbox_mm':box,
                                 'source_sha256':sha256(data).hexdigest()}


def rule_lane(page, record, full, *, extended=False, answer=False):
    """Reserve identical student/answer geometry; draw the complete short rule below."""
    from reportlab.pdfbase import pdfmetrics
    from rule_notes import _lines, rule_text
    if not full:
        return page.height-25
    width = page.width-26
    text = rule_text(record, extended=extended)
    lines = _lines(text, page.font, width, 11)
    ascent, descent = pdfmetrics.getAscentDescent(page.font, 11)
    body_height = (ascent-descent)/MM
    ascent, descent = pdfmetrics.getAscentDescent(page.font, 9.5)
    label_height = (ascent-descent)/MM
    end = page.height-27
    height = label_height+2+len(lines)*body_height+max(0,len(lines)-1)*1.2
    start = end-height
    if not answer:
        page.text('玩法简则', 13, start, 9.5, role='instructions_label')
        y = start+label_height+2
        for line in lines:
            if line:
                page.text(line, 13, y, 11, role='instructions')
            y += body_height+1.2
    page.record['rule_lane_mm'] = [13,start,page.width-13,end]
    return start-6


def puzzle_caption(page, title, record, top, *, hint=False, extended=False):
    from rule_notes import rule_hint
    top += page.text(title, 13, top, 13, role='puzzle_title', bold=True)+3
    cue = rule_hint(record, extended=extended) if hint else ''
    if cue:
        top = page.wrap(cue, 13, top, page.width-26, 10, role='rule_hint')+4
    return top+2
