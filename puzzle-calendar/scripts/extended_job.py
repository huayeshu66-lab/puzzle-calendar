#!/usr/bin/env python3
"""Generate, verify and print a dated calendar using actual extended engines.

source-records.json contains answers and is production material. Player files
are only the separately rendered PDFs. Deduplication covers exact public data,
not D4 equivalence, visual similarity, or difficulty calibration.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

from calendar_plan import plan_calendar

def _csv(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a comma-separated list')
    tokens = [part.strip() for part in value.split(',')]
    if not all(tokens) or len(set(tokens)) != len(tokens):
        raise ValueError(f'{name} contains empty or duplicate entries')
    return tokens


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _hash(record):
    if not isinstance(record.get('public_clues'), (dict,list)):
        raise ValueError('record.public_clues must be structured JSON (object or array)')
    public = {'type_id':record['type_id'], 'public_clues':record['public_clues']}
    return hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',',':')).encode()).hexdigest()


def _proof(report):
    return isinstance(report, dict) and report.get('unique_verified') is True and report.get('answer_rule_checked') is True


def _write(path, value, replace=False):
    with path.open('w' if replace else 'x', encoding='utf-8') as target:
        target.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def run_job(document, *, types, source_project, output_dir, seed='calendar-v1', paper='A4',
            theme='minimal', instructions='first_occurrence', page_ids=None, reuse=None,
            max_attempts=3, total_timeout=600, information=None,appearance=None, variants=None,
            difficulty='challenge'):
    from page_design import normalize_appearance,validate_layout
    appearance=normalize_appearance(appearance)
    started = time.monotonic()
    source, out = Path(source_project).resolve(), Path(output_dir).resolve()
    if out.exists() or out.is_relative_to(source) or source.is_relative_to(out):
        raise ValueError('output-dir must be new and outside the read-only source project')
    if type(seed) is not str or type(max_attempts) is not int or max_attempts <= 0 or not _finite(total_timeout):
        raise ValueError('seed must be text; max-attempts positive integer; total-timeout finite nonnegative')
    if paper not in ('A4','A5') or theme not in ('minimal','newspaper','chinese','modern') or instructions not in ('reference','first_occurrence','every_puzzle','none'):
        raise ValueError('unsupported paper, theme, or instructions mode')
    if not isinstance(document, dict) or document.get('spec_version') != '1.0':
        raise ValueError('plan must have spec_version 1.0')
    fresh = plan_calendar(document.get('request'))
    validate_layout(appearance,fresh['request'],instructions)
    if document.get('plan') != fresh['plan']:
        raise ValueError('plan differs from freshly calculated dates and ownership')
    if information is not None:
        from page_information import prepare_information
        prepare_information(fresh,information)  # Validate full-plan info before starting any generator.
    slots, pages = fresh['plan']['slots'], fresh['plan']['pages']
    selected = _csv(page_ids,'page-ids') if page_ids is not None else [p['page_id'] for p in pages]
    if not selected or set(selected)-{p['page_id'] for p in pages}:
        raise ValueError('page-ids must select real planned pages')
    chosen = [p for p in pages if p['page_id'] in selected]
    if any(len(p['slot_ids']) != 1 for p in chosen) or any(s['puzzles'] != 1 for s in slots):
        raise ValueError('selected pages require one slot and exactly one puzzle per slot')
    from extended_backend import generate_extended, verify_extended, list_capabilities, resolve_variant, select_profiles, UPSTREAM, EIGHT
    selection = select_profiles(source, difficulty=difficulty) if types == 'auto' else None
    choices = selection['types'] if selection is not None else _csv(types,'types')
    available = {row['type_id']:row for row in list_capabilities(source)}
    if any(t not in available or not available[t]['prerequisites_available'] for t in choices):
        raise ValueError('types must name extended engines with available prerequisites')
    explicit_variants = {} if variants is None else copy.deepcopy(variants)
    if not isinstance(explicit_variants, dict):
        raise ValueError('variants must map selected type IDs to reviewed exact specifications')
    variants = copy.deepcopy(selection['variants']) if selection is not None else {}
    variants.update(explicit_variants)
    if not isinstance(variants,dict) or set(variants)-set(choices):
        raise ValueError('variants must map selected type IDs to reviewed exact specifications')
    for kind, value in variants.items():
        if not isinstance(value,str):
            raise ValueError('variant values must be reviewed specification strings')
        resolve_variant(kind,value,source)
    expected_variants = {kind:resolve_variant(kind,variants.get(kind),source) for kind in choices}
    notice = source/'outputs/Puzzle-Publisher-35-Type-Sampler/THIRD-PARTY-NOTICES.txt'
    if not notice.is_file():
        notice = next((source/name for name in ('LICENCE','LICENSE','LICENCE.txt','LICENSE.txt') if (source/name).is_file()), None)
    if notice is None:
        raise ValueError('source third-party notices or license file is missing')
    by_id = {s['slot_id']:s for s in slots}
    schedule = {s['slot_id']:choices[i % len(choices)] for i,s in enumerate(slots)}
    wanted = {p['slot_ids'][0] for p in chosen}
    first_rules = list(dict.fromkeys(next(s['slot_id'] for s in slots if schedule[s['slot_id']]==t) for t in choices if t in schedule.values()))
    records, hashes, ids, attempts, failures, validations = {}, set(), set(), {s:0 for s in by_id}, [], {}
    spent = 0
    if reuse is not None:
        if not isinstance(reuse,dict) or reuse.get('state') not in ('complete','incomplete') or not isinstance(reuse.get('records'),list):
            raise ValueError('reuse must be a complete/incomplete record envelope')
        metrics = reuse.get('metrics',{})
        if not isinstance(metrics,dict):
            raise ValueError('reuse metrics must be an object')
        spent, prior = metrics.get('elapsed_seconds',0), metrics.get('attempts_by_slot',{})
        if not _finite(spent) or not isinstance(prior,dict) or set(prior)-set(by_id) or any(type(n) is not int or n<0 for n in prior.values()):
            raise ValueError('reuse budget metrics are invalid')
        attempts.update(prior)

    def remaining():
        return total_timeout-spent-(time.monotonic()-started)

    def accept(row, original=False):
        sid = row.get('slot_id')
        if sid not in by_id or sid in records:
            raise ValueError('duplicate or unexpected reused slot')
        pid = 'P'+by_id[sid]['date'].replace('-','')
        if row.get('puzzle_id') != pid or row.get('date') != by_id[sid]['date'] or row.get('type_id') != schedule[sid]:
            raise ValueError('record identity, date, or type differs from the full schedule')
        kind = schedule[sid]
        if kind in UPSTREAM and row.get('raw',{}).get('params') != expected_variants[kind]:
            raise ValueError('record variant differs from the requested job specification; refusing difficulty change')
        if kind in EIGHT[:5] and expected_variants[kind] is not None:
            size = row.get('raw', {}).get('size', [])
            if 'x'.join(map(str, size)) != expected_variants[kind]:
                raise ValueError('reused expanded grid differs from requested size')
        digest = _hash(row)
        if row['puzzle_id'] in ids or digest in hashes:
            raise ValueError('duplicate puzzle ID or exact public data')
        if original:
            report = verify_extended(row,source,timeout_seconds=max(.001,remaining()))
            if not _proof(report):
                if remaining() <= 0:
                    raise TimeoutError('budget exhausted during fresh reuse verification')
                raise ValueError('reused answer or board failed fresh verification')
            validations[sid] = report
        elif not _proof(row.get('validation')):
            raise ValueError('generated record lacks a verified unique instance')
        return digest

    # Reuse all full-plan records for the global ledger, including unselected pages.
    for row in reuse['records'] if reuse else []:
        if not isinstance(row,dict):
            raise ValueError('reuse record must be an object')
        if remaining() <= 0:
            failures.append({'reason':'budget exhausted before fresh reuse verification'})
            break
        try:
            digest = accept(row,True)
        except TimeoutError as exc:
            failures.append({'reason':str(exc)})
            break
        records[row['slot_id']] = copy.deepcopy(row)
        hashes.add(digest); ids.add(row['puzzle_id'])
    out.mkdir(parents=True)
    config = {'types':choices,'seed':seed,'source_project':str(source),'paper':paper,'theme':theme,
              'instructions':instructions,'page_ids':[p['page_id'] for p in chosen],
              'first_rules_slots':first_rules,'max_attempts':max_attempts,'total_timeout':total_timeout,
              'appearance':appearance,'variants':variants}
    if selection is not None:
        config['variety_policy'] = selection
    _write(out/'config.json',config)
    if information is not None:_write(out/'information.json',information)
    shutil.copyfile(notice,out/'THIRD-PARTY-NOTICES.txt')
    (out/'print-guide.txt').write_text(f'纸幅 {paper}（'+('210×297mm' if paper=='A4' else '148×210mm')+'），100%／实际大小打印。\n'
        '先打印 print/calibration.pdf 并实测100mm校准尺，再试印题页。\n'
        '单面打印；题本 print/publication.pdf，独立答案 print/answers.pdf，勿混入题页。\n'
        '难度 unrated；来源仅证明本实例有效唯一，未统一校准难度。\n'
        'physical_print_test=pending；visual_qa=pending，需查看实际预览和试印。\n'
        'source-records.json及sources/含完整答案，是制作资料，不自动交给玩家。\n',encoding='utf-8')
    for slot in slots:
        sid = slot['slot_id']
        if sid not in wanted or sid in records:
            continue
        while attempts[sid] < max_attempts and remaining() > 0:
            attempt = attempts[sid]
            attempts[sid] += 1
            kind = schedule[sid]
            seed_parts = [seed,sid,attempt,kind]
            if kind in variants:
                seed_parts.append(variants[kind])
            local_seed = hashlib.sha256(json.dumps(seed_parts,separators=(',',':')).encode()).hexdigest()
            try:
                row = generate_extended(kind,local_seed,out/'sources'/sid/f'attempt-{attempt}',source,
                                        timeout_seconds=remaining(),variant=variants.get(kind))
                row.update(slot_id=sid,puzzle_id='P'+slot['date'].replace('-',''),date=slot['date'])
                digest = accept(row)
                records[sid] = row
                hashes.add(digest); ids.add(row['puzzle_id'])
                break
            except (ValueError,RuntimeError,TimeoutError,OSError) as exc:
                failures.append({'slot_id':sid,'attempt':attempt,'reason':str(exc)})
    missing = [s['slot_id'] for s in slots if s['slot_id'] in wanted and s['slot_id'] not in records]
    envelope = {'schema_version':'1.0','state':'incomplete' if missing else 'complete','content_state':'incomplete' if missing else 'complete','contains_answers':True,
                'audience':'production_only','deduplication_scope':['exact_public_data'],'config':config,
                'selected_slot_ids':[s['slot_id'] for s in slots if s['slot_id'] in wanted],
                'records':[records[s['slot_id']] for s in slots if s['slot_id'] in records],
                'missing_slot_ids':missing,'fresh_reuse_verifications':validations,'failures':failures,
                'metrics':{'attempts_by_slot':attempts,'elapsed_seconds':spent+time.monotonic()-started}}
    _write(out/'source-records.json',envelope)
    def finish(result):
        result['elapsed_seconds'] = spent+time.monotonic()-started
        envelope['metrics']['elapsed_seconds'] = result['elapsed_seconds']
        _write(out/'source-records.json',envelope,replace=True)
        _write(out/'job-report.json',result)
        return result
    if missing:
        return finish({'exit_code':5,'state':'incomplete','output_dir':str(out),'missing_stage':'content','missing_slot_ids':missing})
    try:
        if remaining() <= 0:
            raise TimeoutError('budget exhausted before rendering')
        from extended_calendar import render_extended_calendar
        render_extended_calendar(fresh,[records[s['slot_id']] for s in slots if s['slot_id'] in wanted],
                                 out/'print',source,paper=paper,theme=theme,instructions=instructions,
                                 page_ids=[p['page_id'] for p in chosen],first_rules_slots=first_rules,timeout_seconds=remaining(),
                                 information=information,appearance=appearance)
    except (ValueError,RuntimeError,TimeoutError,OSError) as exc:
        if (out/'print').exists():
            (out/'print').rename(out/'failed-print')
        envelope.update(state='incomplete',missing_stage='render')
        return finish({'exit_code':5,'state':'incomplete','output_dir':str(out),'missing_stage':'render','error':str(exc)})
    return finish({'exit_code':0,'state':'rendered_pending_visual_review','output_dir':str(out),'pages':len(chosen)})

class _Parser(argparse.ArgumentParser):
    def error(self,message):
        raise ValueError(message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    for name in ('plan','types','source-project','output-dir'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--seed',default='calendar-v1')
    parser.add_argument('--paper',choices=('A4','A5'),default='A4')
    parser.add_argument('--theme',choices=('minimal','newspaper','chinese','modern'),default='minimal')
    parser.add_argument('--instructions',choices=('reference','first_occurrence','every_puzzle','none'),default='first_occurrence')
    parser.add_argument('--page-ids'); parser.add_argument('--reuse')
    parser.add_argument('--information',help='Explicitly supplied classified page information JSON')
    parser.add_argument('--appearance',help='JSON page appearance and optional user footer')
    parser.add_argument('--variants',help='JSON map of selected type IDs to reviewed exact upstream variants')
    parser.add_argument('--difficulty', choices=('challenge','mixed'), default='challenge',
                        help='For --types auto: select reviewed candidates across play families')
    parser.add_argument('--max-attempts',type=int,default=3); parser.add_argument('--total-timeout',type=float,default=600)
    try:
        options = vars(parser.parse_args(argv))
        document = json.loads(Path(options.pop('plan')).read_text(encoding='utf-8'))
        reuse_path = options.pop('reuse')
        options['reuse'] = json.loads(Path(reuse_path).read_text(encoding='utf-8')) if reuse_path else None
        information_path=options.pop('information')
        if information_path:
            from render_calendar import read_json
            options['information']=read_json(information_path)
        appearance_path=options.pop('appearance')
        if appearance_path:
            from render_calendar import read_json
            options['appearance']=read_json(appearance_path)
        variants_path=options.pop('variants')
        if variants_path:
            from render_calendar import read_json
            options['variants']=read_json(variants_path)
        result = run_job(document,**options)
    except (ValueError,OSError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False))
    return result['exit_code']


if __name__=='__main__':
    sys.exit(main())
