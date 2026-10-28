#!/usr/bin/env python3
"""Compose verified two-page vector puzzle plates into printable calendars."""
from __future__ import annotations
import argparse
import copy
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import time

from calendar_plan import plan_calendar
from render_calendar import (MM, calibration, header, inspect_pdf, publisher_path,calendar_tokens,
                             read_json, select_plan)


def source_plate(record):
    from pypdf import PdfReader
    path = Path(record['board_pdf'])
    if sha256(path.read_bytes()).hexdigest() != record['board_sha256']:
        raise ValueError('Source board SHA256 mismatch')
    reader = PdfReader(path)
    root = reader.trailer['/Root']
    if (reader.is_encrypted or len(reader.pages)!=2 or reader.attachments or reader.get_fields()
            or any(k in root for k in ('/OCProperties','/OpenAction','/AA'))):
        raise ValueError('Source must be a plain two-page puzzle/answer PDF')
    dimensions, fonts = [], []
    for page in reader.pages:
        if page.get('/Annots') or page.get('/Rotate',0)!=0 or page.images:
            raise ValueError('Source board contains annotations, rotation or raster images')
        dimensions.append((float(page.mediabox.width)/MM,float(page.mediabox.height)/MM))
        def visit(text,cm,tm,font,size):
            if text.strip():
                height = math.hypot(tm[2]*cm[0]+tm[3]*cm[2],tm[2]*cm[1]+tm[3]*cm[3])
                fonts.append(float(size)*height)
        page.extract_text(visitor_text=visit)
    expected = [record['dimensions']['width_mm'],record['dimensions']['height_mm']]
    if any(abs(a-b)>.06 for pair in dimensions for a,b in zip(pair,expected)):
        raise ValueError('Source page dimensions differ from recorded physical geometry')
    if dimensions[0]!=dimensions[1]:
        raise ValueError('Puzzle and answer must share source physical size')
    return reader,dimensions[0],min(fonts) if fonts else None


def normalise_strokes(page, reader, scale):
    """Change only line width: at least 0.5 pt after existing CTM and final scale."""
    from pypdf.generic import ContentStream, FloatObject
    stream = ContentStream(page.get_contents(),reader)
    matrix, stack, changed = (1,0,0,1,0,0), [], 0
    for args,op in stream.operations:
        if op == b'q': stack.append(matrix)
        elif op == b'Q': matrix = stack.pop()
        elif op == b'cm':
            a,b,c,d,e,f = map(float,args); A,B,C,D,E,F = matrix
            matrix=(a*A+b*C,a*B+b*D,c*A+d*C,c*B+d*D,e*A+f*C+E,e*B+f*D+F)
        elif op == b'w':
            factor = math.sqrt(abs(matrix[0]*matrix[3]-matrix[1]*matrix[2]))*scale
            if factor<=0: raise ValueError('Degenerate drawing transform')
            minimum = .5/factor
            if float(args[0])<minimum:
                args[0]=FloatObject(minimum); changed+=1
        elif op in (b'Do',b'BI',b'BDC',b'BMC'):
            raise ValueError('Nested or optional source content is unsupported')
    used,active,font_stack=set(),None,[]
    for args,op in stream.operations:
        if op==b'q':font_stack.append(active)
        elif op==b'Q':active=font_stack.pop()
        elif op==b'Tf':active=args[0]
        elif op in (b'Tj',b'TJ',b"'",b'"') and active is not None:
            used.add(active)
    stream.operations=[(args,op) for args,op in stream.operations if op!=b'Tf' or args[0] in used]
    page.replace_contents(stream)
    fonts=page['/Resources'].get('/Font')
    if fonts is not None:
        fonts=fonts.get_object()
        for name in list(fonts):
            if name not in used:del fonts[name]
    return changed


def overlay(entry, record, request, width, height, font, theme, print_mode, instructions, show, *, answer=False, page_number=1, page_total=1, information_modules=None,appearance=None,source_dimensions=None):
    from reportlab.pdfgen.canvas import Canvas
    from puzzle_publisher.render import _Page
    from page_design import rule_lane, puzzle_caption, draw_footer, normalize_appearance,editorial_caption,editorial_board_bottom
    from pypdf import PdfReader
    data=BytesIO(); cv=Canvas(data,pagesize=(width*MM,height*MM),invariant=1,
                              initialFontName=font,initialFontSize=11)
    page=_Page(cv,font,width,height,[12,12,width-12,height-12],'answer' if answer else 'puzzle',page_number)
    appearance=normalize_appearance(appearance)
    if appearance['layout']=='editorial':
        from calendar_styles import configure_page
        configure_page(page,appearance)
    y=header(page,entry,request['calendar_form'],theme,print_mode,appearance)
    title=record['name_zh']+(' · 答案' if answer else '')
    if appearance['layout']=='editorial':
        bottom=editorial_board_bottom(height,appearance)
        if source_dimensions is None:
            raise ValueError('editorial overlay needs measured source dimensions')
        scale=min((width-26)/source_dimensions[0],(bottom-y)/source_dimensions[1],2.0)
        board_height=source_dimensions[1]*scale
        board_bottom=y+(bottom-y+board_height)/2
        editorial_caption(page,title,board_bottom,information_modules or [],appearance)
    else:
        if information_modules:
            from page_information import draw_information
            y=draw_information(page,information_modules,y,width-26,font_size=11,
                               show_titles=appearance['show_information_titles'])
        y=puzzle_caption(page,title,record,y,
                         hint=appearance['show_rule_hint'] and not show and instructions!='none',extended=True)
        bottom=rule_lane(page,record,show,extended=True,answer=answer)
    draw_footer(page,appearance,record['puzzle_id'],page_number,page_total)
    page.record.update(page_id=entry['page_id'],slot_id=record['slot_id'],puzzle_id=record['puzzle_id'],
                       instructions_shown=show and not answer,calendar_rows=entry['row_count'],
                       information_modules=[{**{k:module[k] for k in ('module_id','kind','classification')},
                                             'provenance':{k:module['provenance'][k]
                                                           for k in ('origin','status','source','method')
                                                           if k in module['provenance']}}
                                            for module in information_modules or []])
    metadata=page.finish(); cv.save(); data.seek(0)
    return PdfReader(data).pages[0],metadata,y,bottom


def render_extended_calendar(document,records,out,source_project,paper='A4',theme='minimal',
                             instructions='first_occurrence',page_ids=None,first_rules_slots=None,
                             font=None,print_mode='bw',timeout_seconds=600,information=None,appearance=None):
    from page_design import normalize_appearance,validate_layout
    appearance=normalize_appearance(appearance)
    if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or timeout_seconds<=0:
        raise ValueError('timeout_seconds must be finite and positive')
    deadline=time.monotonic()+timeout_seconds
    def remaining():
        seconds=deadline-time.monotonic()
        if seconds<=0:raise TimeoutError('Extended calendar render time budget exhausted; nothing published')
        return seconds
    from extended_backend import verify_extended
    from pypdf import PdfWriter, Transformation
    if paper not in ('A4','A5') or theme not in ('minimal','newspaper','chinese','modern'):
        raise ValueError('Unsupported paper or theme')
    if print_mode not in ('bw','color') or instructions not in ('reference','first_occurrence','every_puzzle','none'):
        raise ValueError('Unsupported print or instruction policy')
    information_map={};information_hash=None
    if information is not None:
        from page_information import prepare_information
        information_map=prepare_information(document,information)
        information_hash=sha256(json.dumps(information,sort_keys=True,ensure_ascii=False,
                                          separators=(',',':'),allow_nan=False).encode()).hexdigest()
    document=select_plan(document,page_ids,instructions,first_rules_slots)
    request,plan=document['request'],document['plan']
    validate_layout(appearance,request,instructions)
    if isinstance(records,dict):
        if records.get('state')!='complete' and not (page_ids is not None and records.get('state')=='incomplete'):
            raise ValueError('Full calendar requires complete content records')
        records=records['records']
    if not isinstance(records,list) or not records:
        raise ValueError('Nonempty records list required')
    pages,slots=plan['pages'],plan['slots']; ids=[s['slot_id'] for s in slots]
    owners=[s for p in pages for s in p['slot_ids']]
    if (any(s['puzzles']!=1 for s in slots) or any(len(p['slot_ids'])!=1 for p in pages)
            or len(owners)!=len(set(owners)) or set(owners)!=set(ids)):
        raise ValueError('Baseline supports exactly one puzzle and one slot per page')
    rowmap={r['slot_id']:r for r in records}
    puzzleids=[r['puzzle_id'] for r in records]
    if len(rowmap)!=len(records) or set(rowmap)!=set(ids) or len(set(puzzleids))!=len(puzzleids):
        raise ValueError('Records must map every requested slot exactly once')
    content_hashes=set()
    for row in records:
        remaining()
        if not isinstance(row['puzzle_id'],str) or not row['puzzle_id'] or any(c.isspace() for c in row['puzzle_id']):
            raise ValueError('Invalid puzzle ID')
        raw_answer=row['raw'].get('solution_move',row['raw'].get('answer'))
        if raw_answer!=row['solution']:
            raise ValueError('Source raw answer differs from the verified record answer')
        identity={'type_id':row['type_id'],'params':row['raw'].get('params'),
                  'public':row['raw'].get('description',row['raw'].get('problem',row['raw'].get('puzzle')))}
        digest=sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if digest in content_hashes:raise ValueError('Repeated public puzzle content')
        content_hashes.add(digest)
        proof=verify_extended(row,source_project,timeout_seconds=min(120,remaining()))
        remaining()
        if not proof.get('unique_verified') or not proof.get('answer_rule_checked'):
            raise ValueError('Fresh extended proof failed: '+json.dumps(proof,ensure_ascii=False))
    sys.path.insert(0,str(publisher_path()/'runtime'))
    from puzzle_publisher.render import _font
    registered,fontpath,fonthash=_font(font)
    width,height={'A4':(210,297),'A5':(148,210)}[paper]
    destination=Path(out).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Output directory already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.extended-calendar-',dir=destination.parent))
    writers=[PdfWriter(),PdfWriter()]; reports=[[],[]]; seen=set(); board_inputs=[]
    try:
        for page_number,entry in enumerate(pages,1):
            remaining()
            from rule_notes import extended_rule_key
            row=rowmap[entry['slot_ids'][0]]; key=extended_rule_key(row)
            first=key not in seen if first_rules_slots is None else row['slot_id'] in first_rules_slots
            show=instructions=='every_puzzle' or instructions=='first_occurrence' and first; seen.add(key)
            plate,source_size,smallest_font=source_plate(row)
            overlays=[overlay(entry,row,request,width,height,registered,theme,print_mode,instructions,show,answer=answer,
                              page_number=page_number,page_total=len(pages),
                              information_modules=information_map.get(entry['page_id'],[]),appearance=appearance,
                              source_dimensions=source_size)
                      for answer in (False,True)]
            top=max(item[2] for item in overlays)
            bottom=min(item[3] for item in overlays); available=(width-26,bottom-top)
            scale=min(available[0]/source_size[0],available[1]/source_size[1],2.0)
            cell=float(row['dimensions']['cell_mm'])*scale
            text_pt=smallest_font*scale if smallest_font is not None else None
            if scale<=0 or cell<7-1e-6 or text_pt is not None and text_pt<12-1e-6:
                raise ValueError(f'{row["type_id"]}: layout would fall below 7 mm cells or 12 pt clue text')
            board_width,board_height=[n*scale for n in source_size]
            x=(width-board_width)/2; y=height-top-board_height-(available[1]-board_height)/2
            for answer,(shell,meta,_,_) in enumerate(overlays):
                remaining()
                board_writer=PdfWriter();board=board_writer.add_page(plate.pages[answer])
                changed=normalise_strokes(board,board_writer,scale)
                target=writers[answer].add_page(shell)
                target.merge_transformed_page(board,Transformation().scale(scale).translate(x*MM,y*MM))
                meta.update(scale=scale,cell_mm=cell,minimum_text_pt=text_pt,source_board_sha256=row['board_sha256'],
                            board_bbox_mm=[x,y,board_width,board_height],normalised_line_width_operators=changed,
                            minimum_normalised_stroke_pt=.5,source_plate_semantic_visual_check='pending')
                reports[answer].append(meta)
            board_inputs.append({'slot_id':row['slot_id'],'type_id':row['type_id'],'board_sha256':row['board_sha256']})
        for writer,name in zip(writers,['publication.pdf','answers.pdf']):
            remaining()
            title=(appearance['book_title']+' · 答案' if appearance['book_title'] else '答案') if name=='answers.pdf' else appearance['book_title']
            writer.add_metadata({'/Title':title,'/Author':'Puzzle Calendar'})
            with (stage/name).open('wb') as stream: writer.write(stream)
        ruler=calibration(stage/'calibration.pdf',(width,height),registered)
        guide=None
        if instructions=='reference':
            from rule_notes import write_rule_guide
            guide=write_rule_guide([rowmap[e['slot_ids'][0]] for e in pages],
                                  stage/'guide.pdf',(width,height),registered,extended=True,
                                  top_margin_mm=20 if appearance['style_id']=='cyber-noir' else 12)
        remaining()
        ordered_ids=[rowmap[p['slot_ids'][0]]['puzzle_id'] for p in pages]
        checks={}
        for name in ['publication.pdf','answers.pdf','calibration.pdf']:
            remaining()
            checks[name]=inspect_pdf(stage/name,(width,height),
                                     ordered_ids if name!='calibration.pdf' and appearance['show_puzzle_id'] else None,
                                     ruler=name=='calibration.pdf',
                                     dates=[calendar_tokens(e,request['calendar_form'],appearance['layout']) for e in pages] if name!='calibration.pdf' else None)
        if guide is not None:
            checks['guide.pdf']=inspect_pdf(stage/'guide.pdf',(width,height),[None]*len(guide['pages']))
        report={'student':{'pages':reports[0]},'answers':{'pages':reports[1]},'calibration':ruler,
                'actual_pdf_checks':checks,'visual_qa':'pending','source_vectors':'preserved; only thin line widths raised',
                'source_plate_semantic_visual_check':'pending','font_size_measurement':'source text matrices including CTM, then final scale'}
        if guide is not None:report['guide']=guide
        (stage/'layout-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        manifest={'status':'rendered_pending_visual_review','visual_qa':'pending','physical_print_test':'pending',
                  'difficulty_calibration':'pending','production_ready':False,'source_project':str(Path(source_project).resolve()),
                  'representative_subset':page_ids is not None,'board_inputs':board_inputs,
                  'information_payload_sha256':information_hash,
                  'information_modules':[{'page_id':entry['page_id'],**module}
                                         for entry,meta in zip(pages,reports[0])
                                         for module in meta['information_modules']],
                  'font':{'path':str(fontpath),'sha256':fonthash,'embedded':True},
                  'instructions':instructions,
                  'appearance':appearance,
                  'page_map':[{'page_id':p['page_id'],'slot_id':p['slot_ids'][0],'puzzle_id':rowmap[p['slot_ids'][0]]['puzzle_id']} for p in pages],
                  'files':[{'name':n,'sha256':sha256((stage/n).read_bytes()).hexdigest(),'bytes':(stage/n).stat().st_size,
                            'role':'private_answers' if n=='answers.pdf' else 'public_or_metadata'}
                           for n in ['publication.pdf','answers.pdf','calibration.pdf','layout-report.json']]}
        if guide is not None:
            manifest['files'].append({'name':'guide.pdf','sha256':sha256((stage/'guide.pdf').read_bytes()).hexdigest(),
                                      'bytes':(stage/'guide.pdf').stat().st_size,'role':'public_rules'})
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        remaining()
        destination.mkdir()
        try:
            for item in stage.iterdir():item.rename(destination/item.name)
        except BaseException:
            shutil.rmtree(destination);raise
        return {'output_dir':str(destination),'manifest':str(destination/'manifest.json'),
                'status':manifest['status'],'pages':len(pages)}
    finally:
        shutil.rmtree(stage,ignore_errors=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['plan','records','output-dir','source-project']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--paper',choices=['A4','A5'],default='A4')
    parser.add_argument('--theme',choices=['minimal','newspaper','chinese','modern'],default='minimal')
    parser.add_argument('--instructions',choices=['reference','first_occurrence','every_puzzle','none'],default='first_occurrence')
    parser.add_argument('--page-ids');parser.add_argument('--first-rules-slots');parser.add_argument('--font')
    parser.add_argument('--print-mode',choices=['bw','color'],default='bw')
    parser.add_argument('--timeout-seconds',type=float,default=600)
    parser.add_argument('--information',help='JSON page information, explicitly supplied and classified')
    parser.add_argument('--appearance',help='JSON page appearance and optional user footer')
    args=vars(parser.parse_args(argv))
    try:
        document,records=read_json(args.pop('plan')),read_json(args.pop('records'))
        if args['information'] is not None:args['information']=read_json(args['information'])
        if args['appearance'] is not None:args['appearance']=read_json(args['appearance'])
        if args['first_rules_slots'] is not None:args['first_rules_slots']=read_json(args['first_rules_slots'])
        args['out']=args.pop('output_dir')
        print(json.dumps(render_extended_calendar(document,records,**args),ensure_ascii=False));return 0
    except (ValueError,KeyError,TypeError,OSError,ImportError,TimeoutError) as error:
        print(json.dumps({'error':str(error),'error_type':type(error).__name__},ensure_ascii=False),file=sys.stderr);return 2


if __name__=='__main__':
    raise SystemExit(main())
