"""Original daily-page style presets; source puzzle drawings remain unchanged."""
from copy import deepcopy
import datetime as dt
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re

MM=72/25.4
ASSETS=Path(__file__).resolve().parents[1]/'assets'
STYLE_PRESETS={
    'warm-editorial':{'name_zh':'暖橙编辑','version':'1.0','accent_color':'#F58B1F','display_asset':'WorkSans-Bold.ttf','serif_body':False},
    'swiss-type':{'name_zh':'瑞士大字','version':'1.0','accent_color':'#B6442D','display_asset':'WorkSans-Bold.ttf','serif_body':False},
    'eastern-book':{'name_zh':'东方书卷','version':'1.0','accent_color':'#A84840','display_asset':'Lora-Regular.ttf','serif_body':True},
    'newsprint':{'name_zh':'复古报刊','version':'1.0','accent_color':'#202020','display_asset':'Lora-Regular.ttf','serif_body':True},
    'botanical':{'name_zh':'自然植物','version':'1.0','accent_color':'#476A4F','display_asset':'WorkSans-Regular.ttf','serif_body':False},
    'geometric':{'name_zh':'几何轻趣','version':'1.0','accent_color':'#DFA654','display_asset':'WorkSans-Bold.ttf','serif_body':False},
    'cyber-noir':{'name_zh':'黑白赛博','version':'1.2','accent_color':'#111111','display_asset':'Tektur-Medium.ttf','serif_body':False,'serif_quote':True,'top_safe_mm':20},
}


def get_style(style_id):
    if not isinstance(style_id,str) or style_id not in STYLE_PRESETS:
        raise ValueError('Unknown calendar style_id')
    return deepcopy(STYLE_PRESETS[style_id])


@lru_cache(maxsize=24)
def _registered(path,subfont_index,mtime_ns,size):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    p=Path(path);digest=sha256(p.read_bytes()).hexdigest()
    name='Calendar_'+p.stem.replace('-','')+'_'+digest[:12]+'_'+str(subfont_index)
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name,str(p),subfontIndex=subfont_index))
    return name,{'name':name,'path':str(p),'sha256':digest,'embedded':True,
                 'subfont_index':subfont_index}


def register_font(path,index=0):
    p=Path(path).expanduser().resolve()
    if not p.is_file():raise ValueError('Required calendar font missing: '+str(p))
    stat=p.stat()
    name,meta=_registered(str(p),index,stat.st_mtime_ns,stat.st_size)
    return name,deepcopy(meta)


@lru_cache(maxsize=4)
def _songti_index(path,mtime_ns,size):
    from reportlab.pdfbase.ttfonts import TTFont
    for index in range(16):
        try:
            face=TTFont('CalendarSongtiProbe',path,subfontIndex=index).face
        except Exception:break
        if face.name==b'STSongti-SC-Regular':return index
    raise ValueError('Songti SC-Regular face not found; specify serif_font_path')


def serif_font(appearance):
    """Resolve one embeddable Chinese serif face, shared by body/quote roles."""
    from reportlab.pdfbase import pdfmetrics
    override=appearance.get('serif_font_path')
    path=Path(override).expanduser() if override else Path('/System/Library/Fonts/Supplemental/Songti.ttc')
    if not path.is_file():raise ValueError('This style requires an embeddable Chinese serif font; set serif_font_path')
    stat=path.stat()
    index=0 if override else _songti_index(str(path),stat.st_mtime_ns,stat.st_size)
    name,meta=register_font(path,index)
    face=pdfmetrics.getFont(name).face
    if not all(face.charToGlyph.get(ord(c)) for c in '年月星期一二三四五六日独数宜忌'):
        raise ValueError('Selected serif font lacks required Chinese calendar glyphs')
    return name,meta


def body_font(appearance,default_font):
    from reportlab.pdfbase import pdfmetrics
    style=get_style(appearance['style_id'])
    if style['serif_body']:
        return serif_font(appearance)
    face=pdfmetrics.getFont(default_font).face
    raw=face.filename.decode() if isinstance(face.filename,bytes) else face.filename
    p=Path(raw).resolve()
    return default_font,{'name':default_font,'path':str(p),'sha256':sha256(p.read_bytes()).hexdigest(),'embedded':True}


def configure_page(page,appearance):
    font,metadata=body_font(appearance,page.font)
    page.font=font
    top=get_style(appearance['style_id']).get('top_safe_mm',12)
    page.safe[1]=max(page.safe[1],top)
    if top>12:page.record['binding_reserved_mm']={'edge':'top','depth':top}
    page.record.update(body_font=metadata,style_id=appearance['style_id'],
                       style_version=get_style(appearance['style_id'])['version'])
    page.record['font_roles']={role:deepcopy(metadata) for role in
                              ('calendar_year','calendar_month','weekday','information','puzzle_title')}
    if get_style(appearance['style_id']).get('serif_quote'):
        page.quote_font,quote_metadata=serif_font(appearance)
        page.record['font_roles'].update(quote=quote_metadata,
                                        quote_attribution=deepcopy(quote_metadata))


def _rect(page,x,y,w,h,ink,*,fill=True,weight=.5):
    page.c.saveState()
    page.rect(x,y,w,h,weight=weight,fill=fill,color=ink)
    page.c.restoreState()


def vertical_label(page,value,x,top,size,pitch,role):
    """Upright short Han labels only; preserve full semantics and glyph boxes."""
    from reportlab.pdfbase import pdfmetrics
    if not isinstance(value,str) or not re.fullmatch(r'[\u3400-\u4dbf\u4e00-\u9fff]{2,5}',value):
        raise ValueError('Vertical labels require two to five Han characters, without punctuation')
    ascent,descent=pdfmetrics.getAscentDescent(page.font,size)
    pitch=max(pitch,(ascent-descent)/MM+.4)
    start=len(page.texts)
    for i,char in enumerate(value):
        page.text(char,x,top+i*pitch,size,align='center',role=role+'_glyph')
    glyphs=deepcopy(page.texts[start:])
    box=[min(g['bbox_mm'][j] for g in glyphs) if j<2 else max(g['bbox_mm'][j] for g in glyphs) for j in range(4)]
    page.texts[start:]=[{'text':value,'role':role,'font_pt':size,'bbox_mm':box,
                        'bold':False,'orientation':'vertical-upright','pitch_mm':pitch,'glyphs':glyphs}]
    return box


def date_information(page,modules,appearance):
    """Move selected holidays/solar terms into the cyber date group exactly once."""
    if appearance['style_id']!='cyber-noir':return modules
    from page_information import _module
    rest=[];top=47;start=len(page.texts);ids=[]
    for module in modules:
        if module['kind'] not in ('holiday','solar_term'):
            rest.append(module);continue
        item=_module(module);ids.append(item['module_id'])
        values=[field['value'] for field in item['fields']] if 'fields' in item else [item['text']]
        for value in values:
            match=re.fullmatch(r'([\u3400-\u9fff]{2,5})(?:\s+(\d{2}:\d{2}))?',value)
            if match:
                name,time=match.groups()
                from reportlab.pdfbase import pdfmetrics
                width=pdfmetrics.stringWidth(name,page.font,12)/MM
                top_end=top+page.text(name,62,top,12,role='date_event',bold=True)
                if time:
                    top_end=max(top_end,top+.5+page.text(time,62+width+2,top+.5,11,role='date_event_time'))
                top=top_end+1.5
            else:
                top=page.wrap(value,62,top,52,11,role='date_event')+1.5
            if top>63.5:raise ValueError('Selected holiday/solar term information exceeds the date area; recompose without dropping it')
    page.record['date_information_module_ids']=ids
    if ids:
        drawn=page.texts[start:]
        page.record['date_information_bbox_mm']=[min(t['bbox_mm'][j] for t in drawn) if j<2 else max(t['bbox_mm'][j] for t in drawn) for j in range(4)]
    return rest


def _leaves(page,ink):
    page.line(112,51,130,17,.7,ink)
    for x,y,side in [(126,25,1),(122,32,-1),(117,41,1),(113,48,-1)]:
        points=[(x,y),(x+side*8,y-1),(x+side*8,y-6),(x+side*6,y-7),
                (x+side*2,y-7),(x-side,y-2),(x,y)]
        page.bounds([min(p[0] for p in points)-.2,min(p[1] for p in points)-.2,
                     max(p[0] for p in points)+.2,max(p[1] for p in points)+.2])
        cv=page.c;cv.saveState();cv.setStrokeColor(ink);cv.setLineWidth(.65)
        path=cv.beginPath();path.moveTo(x*MM,(page.height-y)*MM)
        for start in (1,4):
            coords=[]
            for px,py in points[start:start+3]:coords.extend([px*MM,(page.height-py)*MM])
            path.curveTo(*coords)
        path.close();cv.drawPath(path,stroke=1,fill=0);cv.restoreState()
    page.record['ornament']='original_vector_leaf_branch'


def draw_header(page,entry,appearance,print_mode):
    from reportlab.lib import colors
    style=get_style(appearance['style_id']);ident=appearance['style_id']
    display,meta=register_font(ASSETS/style['display_asset'])
    date=dt.date.fromisoformat(entry['unit_key']);left,_,right,_=page.safe
    accent=colors.HexColor(appearance['accent_color']) if print_mode=='color' else colors.black
    year,month,day,weekday=str(date.year),f'{date.month}月',f'{date.day:02d}','星期'+'一二三四五六日'[date.weekday()]
    def text(value,x,y,size,role,align='left',numeric=False):
        original=page.font
        if numeric:page.font=display
        try:page.text(value,x,y,size,role=role,align=align)
        finally:page.font=original
    if ident=='warm-editorial':
        if print_mode=='color':_rect(page,left+.5,13,right-left-1,47,accent)
        else:page.line(left+1,60,right-1,60,.6)
        text(year,left+6,20,11,'calendar_year');text(month,left+6,28,22,'calendar_month')
        text(weekday,left+6,43,14,'weekday');text(day,right-6,18,68,'calendar_day','right',True)
    elif ident=='swiss-type':
        text(day,left+1,12.5,76,'calendar_day',numeric=True)
        text(year,right-1,16,11,'calendar_year','right');text(month,right-1,25,22,'calendar_month','right')
        text(weekday,right-1,42,14,'weekday','right');page.line(left+1,58,left+20,58,2,accent)
    elif ident=='eastern-book':
        text(year,left+1,16,11,'calendar_year');text(month,page.width/2,13,22,'calendar_month','center')
        text(weekday,right-1,16,12,'weekday','right');text(day,page.width/2,25,64,'calendar_day','center',True)
        page.line(left+1,59,page.width/2-22,59,.7,accent)
        page.line(page.width/2+22,59,right-1,59,.7,accent)
    elif ident=='newsprint':
        for y,w in [(13,.9),(15,.5),(58,.5),(60,.9)]:page.line(left+1,y,right-1,y,w,accent)
        text(year,left+1,24,11,'calendar_year');text(month,left+1,33,22,'calendar_month')
        text(day,page.width/2,22,64,'calendar_day','center',True);text(weekday,right-1,38,12,'weekday','right')
    elif ident=='botanical':
        text(day,left+1,17,68,'calendar_day',numeric=True)
        text(year,left+46,15,11,'calendar_year');text(month,left+46,24,22,'calendar_month')
        text(weekday,left+46,42,14,'weekday');_leaves(page,accent)
    elif ident=='geometric':
        _rect(page,left+.5,13,39,47,accent,fill=print_mode=='color')
        second=colors.HexColor('#E9E3D8') if print_mode=='color' else colors.black
        _rect(page,left+43,13,right-left-43.5,47,second,fill=print_mode=='color')
        text(year,left+5,20,11,'calendar_year');text(month,left+5,29,22,'calendar_month')
        text(weekday,left+5,45,12,'weekday');text(day,right-5,20,68,'calendar_day','right',True)
    else:
        text(day,left+2,24,84,'calendar_day',numeric=True)
        text(year,62,23,11,'calendar_year')
        text(month,62,31,22,'calendar_month')
        vertical_label(page,weekday,right-5,27,12,4.8,'weekday')
        # One shared edge relates the date group to the puzzle, without chrome.
        page.line(left+2,66,right-20,66,.6)
        page.line(right-20,66,right-16,62,.6)
        page.line(right-16,62,right-2,62,.6)
        page.record['ornament']='single_cut_corner_date_divider'
    page.record.update(display_font=meta,date_iso=date.isoformat(),layout='editorial',
                       style_id=ident,style_version=style['version'])
    page.record.setdefault('font_roles',{})['calendar_day']=meta
    return 70 if ident=='cyber-noir' else 66
