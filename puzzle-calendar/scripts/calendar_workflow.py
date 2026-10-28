#!/usr/bin/env python3
"""Reusable task record and revision/release orchestration; no fabricated design or evidence."""
from __future__ import annotations
import argparse
import copy
import datetime as dt
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

VERSION='2.0'
ROLES=frozenset('calendar answers rules calibration punch_guide preview print_notes sources request_data plan records board information renderer_manifest layout_report qa design other_private'.split())
KINDS=frozenset('content pdf visual user_acceptance physical_print human_difficulty'.split())
RENDER_ROLES=frozenset('calendar answers rules calibration punch_guide preview renderer_manifest layout_report qa'.split())
PLAN_FIELDS=frozenset('date_range calendar_form cadence puzzles_per_slot week_start weekdays dates include_dates exclude_dates'.split())


def read_json(path):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('Duplicate JSON key: '+k)
            result[k]=v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=pairs,
                      parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:
        temp=Path(f.name);f.write(data)
    try:os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def _string(value,name):
    if not isinstance(value,str) or not value.strip():raise ValueError(name+' must be nonempty text')
    return value


def _identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value):
        raise ValueError('Unsafe or invalid identifier')
    return value


def _request(value):
    if not isinstance(value,dict) or set(value)-{'requirements','decisions','constraints','scope'}:
        raise ValueError('request uses requirements, decisions, constraints and optional scope')
    result=copy.deepcopy(value)
    for key in ('requirements','decisions','constraints'):
        result.setdefault(key,{})
        if not isinstance(result[key],dict):raise ValueError(key+' must be an object')
    for path,decision in result['decisions'].items():
        _string(path,'decision path')
        if not isinstance(decision,dict) or set(decision)-{'origin','reason'}:
            raise ValueError('Decision stores origin/reason only; actual value belongs in requirements')
        if decision.get('origin') not in ('user','assumed','delegated','derived'):
            raise ValueError('Invalid decision origin')
        _string(decision.get('reason'),'decision reason')
    for key in ('locked','excluded_types'):
        result['constraints'].setdefault(key,[])
        if not isinstance(result['constraints'][key],list) or any(not isinstance(x,str) for x in result['constraints'][key]):
            raise ValueError('constraints.'+key+' must be a text list')
    return result


def load_job(location):
    path=Path(location).expanduser().resolve()
    if path.is_dir():path=path/'job.json'
    job=read_json(path)
    if job.get('schema_version')!=VERSION or type(job.get('revision')) is not int or job['revision']<1:
        raise ValueError('Unsupported or malformed job record')
    _identifier(job.get('job_id'));_request(job.get('request'))
    for key in ('artifacts','reviews','history'):
        if not isinstance(job.get(key),list):raise ValueError('Malformed '+key)
    if not isinstance(job.get('brief'),dict):raise ValueError('brief must be an object')
    return job,path.parent


def init_job(request,brief,output):
    request=_request(request)
    if not isinstance(brief,dict):raise ValueError('brief must be an object')
    root=Path(output).expanduser().resolve()
    if root.exists():raise ValueError('Task directory already exists; resume instead of overwriting')
    job={'schema_version':VERSION,'job_id':_identifier(root.name),'revision':1,
         'request':request,'brief':copy.deepcopy(brief),'artifacts':[],'reviews':[],
         'history':[{'revision':1,'action':'init','notes':'Requirement values are stored once; no approval inferred'}]}
    root.mkdir(parents=True);write_json(root/'job.json',job)
    return job


def _active(job,role=None):
    return [a for a in job['artifacts'] if a.get('active',True) and (role is None or a['role']==role)]


def _basis(job):
    return sha256(json.dumps({'request':job['request'],'brief':job['brief']},sort_keys=True,
        ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _artifact_path(root,artifact):
    value=artifact.get('path')
    if not isinstance(value,str) or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('Artifact path must stay relative to task')
    path=root/value
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe artifact path')
    if not path.is_file() or sha256(path.read_bytes()).hexdigest()!=artifact['sha256'] or path.stat().st_size!=artifact['bytes']:
        raise ValueError('Artifact missing or changed: '+artifact['id'])
    return path


def _missing(job):
    r=job['request']['requirements'];missing=[]
    for key in ('date_range','calendar_form','cadence','audience','difficulty','print','output','instructions','appearance'):
        if key not in r:missing.append(key)
    for group,keys in [('print',('paper','orientation','mode','duplex','binding')),('output',('formats','answers'))]:
        if isinstance(r.get(group),dict):missing.extend(group+'.'+k for k in keys if k not in r[group])
    if isinstance(r.get('appearance'),dict):
        missing.extend('appearance.'+k for k in ('layout','style_id') if k not in r['appearance'])
    brief=job['brief']
    for k in ('use_case','priorities','rationale','regions','tradeoffs'):
        if k not in brief or brief[k] in ('',None,{},[]) and k!='tradeoffs':missing.append('brief.'+k)
    if 'priorities' in brief and (not isinstance(brief['priorities'],list) or not all(isinstance(v,str) for v in brief['priorities'])):
        raise ValueError('brief.priorities must be a list of information roles')
    return missing


def _resolve_records(payload,root):
    records=copy.deepcopy(payload);rows=records.get('records',[]) if isinstance(records,dict) else records
    if not isinstance(rows,list):raise ValueError('records must be a list or an envelope')
    for row in rows:
        if 'board_pdf' in row:
            p=Path(row['board_pdf'])
            if p.is_absolute():raise ValueError('Canonical board paths must be task-relative; use import_records')
            p=(root/p).resolve()
            if not p.is_relative_to(root) or not p.is_file():raise ValueError('Missing portable board')
            if sha256(p.read_bytes()).hexdigest()!=row['board_sha256']:raise ValueError('Portable board SHA mismatch')
            row['board_pdf']=str(p)
    return records


def prepare_job(location):
    from calendar_plan import plan_calendar
    from page_design import normalize_appearance,validate_layout
    job,root=load_job(location);missing=_missing(job)
    if missing:return {'state':'needs_intake_or_brief','missing':missing,'request_preserved':True}
    r=job['request']['requirements'];issues=[]
    planner={key:copy.deepcopy(r[key]) for key in PLAN_FIELDS if key in r}
    plan=plan_calendar(planner)
    try:appearance=normalize_appearance(r['appearance'])
    except ValueError as e:
        appearance=copy.deepcopy(r['appearance']);issues.append(str(e))
    printing=r['print'];output=r['output']
    if not isinstance(printing,dict) or not isinstance(output,dict):raise ValueError('print/output must be objects')
    if printing['paper'] not in ('A4','A5'):issues.append('Requested paper needs another renderer')
    if printing['orientation'] not in ('portrait','landscape'):issues.append('Requested orientation needs implementation')
    if printing['mode'] not in ('bw','color'):issues.append('Requested print mode needs implementation')
    if type(printing['duplex']) is not bool:raise ValueError('print.duplex must be boolean')
    if printing['duplex']:issues.append('Duplex imposition/back-side alignment is not implemented by baseline renderers')
    if not isinstance(output['formats'],list) or not output['formats']:raise ValueError('output.formats must be a nonempty list')
    if set(output['formats'])-{'pdf'}:issues.append('Requested editable/non-PDF output needs an actual document adapter')
    if output['answers']!='separate':issues.append('Requested answer arrangement needs implementation')
    if not issues:
        try:validate_layout(appearance,plan['request'],r['instructions'],printing['orientation'])
        except ValueError as e:issues.append(str(e))
    binding=printing['binding']
    if not isinstance(binding,dict) or binding.get('edge') not in ('none','top','left','right','bottom') or type(binding.get('reserve_mm')) not in (int,float) or not 0<=binding['reserve_mm']<=100:
        raise ValueError('binding requires an edge and finite nonnegative reserve_mm')
    if binding['edge']=='none' and binding['reserve_mm']!=0:
        issues.append('A binding reserve with edge=none cannot be silently ignored')
    if binding['edge']!='none':
        supported=(appearance['layout']=='editorial' and appearance['style_id']=='cyber-noir' and binding['edge']=='top' and binding['reserve_mm']<=20)
        if not supported:issues.append('Requested binding reserve needs measured layout support; it is not implemented by this baseline')
    scope=job['request'].get('scope',r['date_range'])
    start,end=dt.date.fromisoformat(scope['start']),dt.date.fromisoformat(scope['end'])
    full=r['date_range']
    if start>end or scope['start']<full['start'] or scope['end']>full['end']:raise ValueError('Current delivery scope must stay inside planned date range')
    pages=[p['page_id'] for p in plan['plan']['pages'] if any(scope['start']<=d<=scope['end'] for d in p['dates'])]
    if not pages:raise ValueError('Current scope selects no actual pages')
    inputs=root/'inputs';inputs.mkdir(exist_ok=True)
    write_json(inputs/'plan.json',plan);write_json(inputs/'appearance.json',appearance)
    exported={'plan':'inputs/plan.json','appearance':'inputs/appearance.json'}
    needed_inputs=[]
    for role,name in [('information','information.json'),('records','records-resolved.json')]:
        candidates=_active(job,role)
        target=inputs/name
        if len(candidates)>1:raise ValueError('Only one active '+role+' artifact is allowed')
        if candidates:
            payload=read_json(_artifact_path(root,candidates[0]))
            if role=='records':payload=_resolve_records(payload,root)
            else:
                from page_information import prepare_information
                prepared=prepare_information(plan,payload)
                actual={m['kind'] for values in prepared.values() for m in values}
                wanted=set(r.get('information',{}).get('kinds',[]))
                if actual-wanted:issues.append('Information data includes kinds not selected in requirements: '+','.join(sorted(actual-wanted)))
            write_json(target,payload);exported[role]='inputs/'+name
        else:
            target.unlink(missing_ok=True)
            if role=='information' and r.get('information',{}).get('kinds'):needed_inputs.append('selected_information_data')
    result={'state':'needs_implementation' if issues else 'needs_inputs' if needed_inputs else 'prepared','revision':job['revision'],
            'basis_sha256':_basis(job),
            'scope':scope,'planned_pages':plan['plan']['totals']['content_pages'],'selected_page_ids':pages,
            'issues':issues,'needed_inputs':needed_inputs,'inputs':exported,'design_brief':job['brief'],
            'render_options':{'paper':printing['paper'],'orientation':printing['orientation'],'print_mode':printing['mode'],'instructions':r['instructions']},
            'support_claim':'Planner and configuration preflight only; generation, print fit and visual quality require actual evidence'}
    write_json(inputs/'prepared.json',result)
    return result


def attach_artifacts(location,specifications):
    job,root=load_job(location)
    if not isinstance(specifications,list) or not specifications:raise ValueError('Artifact spec must be a nonempty list')
    old={a['id']:a for a in job['artifacts']};ids=set();prepared=[]
    for spec in specifications:
        if not isinstance(spec,dict) or set(spec)-{'id','role','path','source_pdf_ids'}:raise ValueError('Unknown artifact specification fields')
        ident=_identifier(spec.get('id'))
        if ident in ids:raise ValueError('Duplicate artifact id')
        ids.add(ident)
        if spec.get('role') not in ROLES:raise ValueError('Unknown artifact role')
        source=Path(spec['path']).expanduser().resolve()
        if not source.is_file():raise ValueError('Artifact source missing')
        data=source.read_bytes();digest=sha256(data).hexdigest()
        suffix=source.suffix if re.fullmatch(r'\.[A-Za-z0-9]{1,12}',source.suffix) else '.bin'
        relative=f'artifacts/{ident}-{digest[:12]}{suffix}'
        meta={'id':ident,'role':spec['role'],'path':relative,'sha256':digest,'bytes':len(data),'revision':job['revision']+1,'active':True}
        if suffix.lower()=='.pdf':
            from pypdf import PdfReader
            pdf=PdfReader(source)
            if pdf.is_encrypted:raise ValueError('Encrypted PDF not accepted as a registered output')
            meta['page_count']=len(pdf.pages)
        prepared.append((meta,data,spec.get('source_pdf_ids')))
    latest={**old,**{a['id']:a for a,_,_ in prepared}}
    for meta,data,source_ids in prepared:
        if meta['role']=='preview':
            if not isinstance(source_ids,list) or not source_ids:raise ValueError('Preview must declare current source_pdf_ids')
            parents={}
            for ident in source_ids:
                parent=latest.get(ident)
                if parent is None or not parent.get('active',True) or not parent['path'].lower().endswith('.pdf'):
                    raise ValueError('Preview references missing or inactive PDF')
                parents[ident]=parent['sha256']
            meta.update(source_pdf_ids=source_ids,source_pdf_sha256=parents)
        elif source_ids is not None:raise ValueError('source_pdf_ids is only meaningful for previews')
    # No writes until every spec has been validated.
    for meta,data,_ in prepared:
        target=root/meta['path'];target.parent.mkdir(exist_ok=True);target.write_bytes(data)
    job['revision']+=1
    job['artifacts']=[a for a in job['artifacts'] if a['id'] not in ids]+[a for a,_,_ in prepared]
    upstream_changed=any(a['role'] in {'records','board','information','plan'} and
        (a['id'] not in old or a['sha256']!=old[a['id']]['sha256']) for a,_,_ in prepared)
    for artifact in job['artifacts']:
        if upstream_changed and artifact['id'] not in ids and artifact['role'] in RENDER_ROLES:
            artifact['active']=False
        if artifact['id'] not in ids and artifact['role']=='preview' and any(
                latest.get(i,{}).get('sha256')!=h for i,h in artifact.get('source_pdf_sha256',{}).items()):
            artifact['active']=False
    job['history'].append({'revision':job['revision'],'action':'attach','artifact_ids':sorted(ids),
        'upstream_changed':upstream_changed,'existing_renders_retired':upstream_changed})
    write_json(root/'job.json',job)
    return {'revision':job['revision'],'registered':sorted(ids)}


def import_records(location,source):
    """Copy frozen record/board assets; export absolute working paths only in prepare."""
    job,root=load_job(location);payload=read_json(source)
    rows=payload.get('records') if isinstance(payload,dict) else payload
    if not isinstance(rows,list):raise ValueError('Invalid records envelope')
    canonical=copy.deepcopy(payload);target_rows=canonical['records'] if isinstance(canonical,dict) else canonical
    board_specs=[];board_ids={}
    for row,new in zip(rows,target_rows):
        if 'board_pdf' not in row:continue
        path=Path(row['board_pdf'])
        if not path.is_absolute():path=Path(source).resolve().parent/path
        digest=sha256(path.read_bytes()).hexdigest()
        if digest!=row['board_sha256']:raise ValueError('Source board SHA mismatch')
        ident=_identifier('board-'+row.get('puzzle_id',row.get('slot_id')))
        if ident in board_ids:raise ValueError('Duplicate record board identity')
        board_ids[ident]=new;board_specs.append({'id':ident,'role':'board','path':str(path)})
    if board_specs:
        attach_artifacts(root,board_specs)
        updated,_=load_job(root)
        for artifact in updated['artifacts']:
            if artifact['id'] in board_ids:board_ids[artifact['id']]['board_pdf']=artifact['path']
    destination=root/'inputs'/'imported-records.json';write_json(destination,canonical)
    result=attach_artifacts(root,[{'id':'records','role':'records','path':str(destination)}])
    return {**result,'records':len(rows),'portable_boards':len(board_specs)}


def record_review(location,report):
    job,root=load_job(location);report=copy.deepcopy(report)
    if not isinstance(report,dict) or report.get('kind') not in KINDS:raise ValueError('Unknown review kind')
    if report.get('status') not in ('passed','failed','pending','not_requested'):raise ValueError('Unknown review status')
    for key in ('notes','reviewer'):_string(report.get(key),key)
    _identifier(report.get('id'))
    scope=report.get('scope')
    if not isinstance(scope,list) or not scope or len(scope)!=len(set(scope)):raise ValueError('Review needs explicit unique artifact scope')
    lookup={a['id']:a for a in _active(job)};hashes={}
    for ident in scope:
        if ident not in lookup:raise ValueError('Review references inactive or absent artifact')
        _artifact_path(root,lookup[ident]);hashes[ident]=lookup[ident]['sha256']
    supplied=report.get('artifact_sha256')
    if supplied is not None and supplied!=hashes:raise ValueError('Review report does not describe current artifact hashes')
    delivery_scope=job['request'].get('scope',job['request']['requirements'].get('date_range'))
    basis=_basis(job)
    if 'delivery_scope' in report and report['delivery_scope']!=delivery_scope:raise ValueError('Review report describes a different delivery scope')
    if 'basis_sha256' in report and report['basis_sha256']!=basis:raise ValueError('Review report describes different requirements or design brief')
    if report['status']=='passed' and (not isinstance(report.get('criteria'),dict) or not report['criteria']):
        raise ValueError('Passed review needs concrete criteria; a status flag alone is not evidence')
    report.update(artifact_sha256=hashes,revision=job['revision'],delivery_scope=delivery_scope,basis_sha256=basis)
    job['reviews']=[r for r in job['reviews'] if r['id']!=report['id']]+[report]
    job['history'].append({'revision':job['revision'],'action':'review','review_id':report['id']})
    write_json(root/'job.json',job)
    return {'recorded':report['id'],'kind':report['kind'],'status':report['status']}


def make_previews(location,pdf_ids,executable=None):
    """Render actual registered PDFs into repeatable 16-page contact sheets."""
    from PIL import Image,ImageDraw
    job,root=load_job(location);lookup={a['id']:a for a in _active(job)}
    binary=executable or shutil.which('pdftoppm')
    if not binary:raise ValueError('Resolve the available Poppler executable and pass --pdftoppm')
    if not isinstance(pdf_ids,list) or not pdf_ids or len(set(pdf_ids))!=len(pdf_ids):raise ValueError('Choose unique registered PDF ids')
    sources={ident:_artifact_path(root,lookup[ident]) for ident in pdf_ids}
    specs=[]
    with tempfile.TemporaryDirectory(prefix='calendar-previews-') as scratch:
        folder=Path(scratch)
        for ident,source in sources.items():
            if source.suffix.lower()!='.pdf':raise ValueError('Preview source must be a registered PDF')
            prefix=folder/ident
            subprocess.run([str(binary),'-scale-to','900','-png',str(source),str(prefix)],check=True,
                           timeout=60,capture_output=True)
            pages=sorted(folder.glob(ident+'-*.png'))
            if len(pages)!=lookup[ident].get('page_count'):raise ValueError('Rendered preview count differs from actual PDF pages')
            for batch in range((len(pages)+15)//16):
                group=pages[batch*16:(batch+1)*16]
                columns=min(4,len(group));rows=(len(group)+columns-1)//columns
                sheet=Image.new('RGB',(310*columns,470*rows),'#e8e8e8');draw=ImageDraw.Draw(sheet)
                for i,path in enumerate(group):
                    with Image.open(path) as original:
                        thumb=original.convert('RGB');thumb.thumbnail((290,430))
                    x=i%columns*310+(310-thumb.width)//2;y=i//columns*470+24
                    sheet.paste(thumb,(x,y));draw.text((x,y-16),str(batch*16+i+1),fill='black')
                output=folder/f'contact-{ident}-{batch+1}.png';sheet.save(output)
                specs.append({'id':_identifier(f'preview-{ident}-{batch+1}'),'role':'preview','path':str(output),'source_pdf_ids':[ident]})
        result=attach_artifacts(root,specs)
    return {**result,'source_pdf_ids':pdf_ids,'purpose':'Actual-page contact sheets; rendering does not constitute visual approval'}


def _merge(original,patch):
    if not isinstance(original,dict) or not isinstance(patch,dict):return copy.deepcopy(patch)
    result=copy.deepcopy(original)
    for k,v in patch.items():result[k]=_merge(result.get(k),v)
    return result


def _changes(a,b,prefix=''):
    if isinstance(a,dict) and isinstance(b,dict):
        result=[]
        for k in sorted(set(a)|set(b)):result+=_changes(a.get(k),b.get(k),prefix+'.'+k if prefix else k)
        return result
    return [] if a==b else [prefix]


def revise_job(location,patch,reason,origin='derived'):
    job,root=load_job(location);_string(reason,'revision reason')
    if origin not in ('user','derived'):raise ValueError('revision origin must be user or derived')
    if not isinstance(patch,dict) or not patch or set(patch)-{'request','brief'}:raise ValueError('Revision patch may update request/brief only')
    candidate=_merge(job,patch);candidate['request']=_request(candidate['request'])
    if not isinstance(candidate['brief'],dict):raise ValueError('brief must remain an object')
    changed=_changes({'request':job['request'],'brief':job['brief']},{'request':candidate['request'],'brief':candidate['brief']})
    if not changed:return {'changed':[],'revision':job['revision'],'stages':[]}
    locked=job['request']['constraints']['locked']
    if origin!='user' and set(locked)-set(candidate['request']['constraints']['locked']):
        raise ValueError('A locked user requirement cannot be unlocked by an internal revision')
    if origin!='user' and any(c.startswith('request.requirements.'+key) or ('request.requirements.'+key).startswith(c+'.') for c in changed for key in locked):
        raise ValueError('A locked user requirement can change only for an explicit user revision')
    content=any(any(c.startswith('request.requirements.'+f) for f in PLAN_FIELDS|{'difficulty','types'}) or c.startswith('request.constraints.excluded_types') for c in changed)
    planning=any(c.startswith('request.scope') or any(c.startswith('request.requirements.'+f) for f in PLAN_FIELDS) for c in changed)
    brief_review=any(c.startswith('brief') for c in changed)
    value_change=content or any(c.startswith(('request.requirements.','request.scope')) or
        c.startswith('brief') and c!='brief.rationale' for c in changed)
    roles=set(RENDER_ROLES) if value_change else set()
    if content:roles|={'records','plan'}
    if planning:roles.add('plan')
    if any(c.startswith('request.requirements.information') for c in changed):roles.add('information')
    for a in candidate['artifacts']:
        if a['role'] in roles:a['active']=False
    stages=(['plan'] if planning else [])+(['content'] if content else [])+(['layout','pdf','visual','release'] if value_change else [])
    if brief_review and not value_change:stages=['design_review','release']
    candidate['revision']=job['revision']+1
    invalidated={'pdf','visual'} if value_change else set()
    if brief_review:invalidated|={'visual','user_acceptance'}
    if content:invalidated.add('content')
    if value_change:invalidated|={'user_acceptance','physical_print','human_difficulty'}
    for review in candidate['reviews']:
        if review['kind'] in invalidated:
            review['invalidated_by_revision']=candidate['revision'];review['invalidated_reason']=reason
    event={'revision':candidate['revision'],'action':'revise','origin':origin,'reason':reason,'changed':changed,
           'stages':stages,'preserved_content':not content,'notes':'Source content proof may be reused by hash; new output mappings still need checking'}
    candidate['history'].append(event);write_json(root/'job.json',candidate)
    return event


def status_job(location):
    job,root=load_job(location)
    from calendar_release import evaluate_job
    status=evaluate_job(job,root)
    path=root/'inputs/prepared.json'
    preflight={'state':'not_run','action':'Run prepare to inspect current configuration support'}
    if path.exists():
        try:
            prepared=read_json(path)
            if prepared.get('basis_sha256')!=_basis(job):
                preflight={'state':'stale','action':'Run prepare after the requirement or brief change'}
            else:
                preflight={k:prepared[k] for k in ('state','issues','needed_inputs','missing') if k in prepared}
        except (ValueError,OSError,TypeError) as e:
            preflight={'state':'failed','error':str(e)}
    return {'job_id':job['job_id'],'revision':job['revision'],'missing_intake_or_brief':_missing(job),
            'configuration_preflight':preflight,
            'current_scope':job['request'].get('scope',job['request']['requirements'].get('date_range')),
            'last_change':job['history'][-1] if job['history'] else None,**status}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='action',required=True)
    p=subs.add_parser('init');p.add_argument('--request',required=True);p.add_argument('--brief',required=True);p.add_argument('--output',required=True)
    for action in ['prepare','status','attach','review','revise','import-records','preview','release']:
        p=subs.add_parser(action);p.add_argument('--job',required=True)
        if action=='attach':p.add_argument('--spec',required=True)
        elif action=='review':p.add_argument('--report',required=True)
        elif action=='revise':p.add_argument('--patch',required=True);p.add_argument('--reason',required=True);p.add_argument('--origin',choices=['user','derived'],default='derived')
        elif action=='import-records':p.add_argument('--records',required=True)
        elif action=='preview':p.add_argument('--pdf-ids',required=True);p.add_argument('--pdftoppm')
        elif action=='release':p.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:
        if args.action=='init':result=init_job(read_json(args.request),read_json(args.brief),args.output)
        elif args.action=='prepare':result=prepare_job(args.job)
        elif args.action=='status':result=status_job(args.job)
        elif args.action=='attach':result=attach_artifacts(args.job,read_json(args.spec))
        elif args.action=='review':result=record_review(args.job,read_json(args.report))
        elif args.action=='revise':result=revise_job(args.job,read_json(args.patch),args.reason,args.origin)
        elif args.action=='import-records':result=import_records(args.job,args.records)
        elif args.action=='preview':result=make_previews(args.job,args.pdf_ids.split(','),args.pdftoppm)
        else:
            from calendar_release import build_release
            job,root=load_job(args.job);result=build_release(job,root,args.output)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as e:
        print(json.dumps({'state':'failed','error':str(e)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
