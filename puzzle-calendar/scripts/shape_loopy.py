#!/usr/bin/env python3
"""Fresh non-square Loopy specimens: native geometry, independent loop proof.

The upstream source project is read-only. A tiny graph exporter is compiled in
the new output directory against its existing libcore.a; no PDF is authored.
Native success alone is never uniqueness evidence. Difficulty is uncalibrated.
Without an explicit native variant, honeycomb uses a balanced hexagonal cluster.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
SOURCE_REL = 'work/tatham-source/puzzles-20260923.616da16'
TYPES = {1: 'triangular', 2: 'honeycomb'}
REVIEWED_PARAMS = {'5x5t2dh', '5x5t1dh', '7x7t1dh'}
EXPORT_C = r'''
#include "grid.h"
#include <stdarg.h>
void frontend_default_colour(frontend *fe,float *o){o[0]=o[1]=o[2]=1.0F;}
void get_random_seed(void **p,int *n){*p=dupstr("geometry-export");*n=15;}
void deactivate_timer(frontend *fe){}
void activate_timer(frontend *fe){}
void fatal(const char *fmt,...){va_list ap;va_start(ap,fmt);vfprintf(stderr,fmt,ap);va_end(ap);exit(1);}
int main(int argc,char **argv){
 if(argc!=5)return 2;
 int t=atoi(argv[1]),w=atoi(argv[2]),h=atoi(argv[3]);grid_type gt;
 switch(t){case 1:gt=GRID_TRIANGULAR;break;case 2:gt=GRID_HONEYCOMB;break;
 default:return 3;}
 const char *desc=argv[4][0]?argv[4]:NULL,*err=grid_validate_params(gt,w,h);
 if(err){fprintf(stderr,"%s",err);return 4;}
 err=grid_validate_desc(gt,w,h,desc);if(err){fprintf(stderr,"%s",err);return 5;}
 grid *g=grid_new(gt,w,h,desc);
 printf("{\"nodes\":[");
 for(int i=0;i<g->num_dots;i++){grid_dot *d=g->dots[i];printf("%s[%d,%d]",i?",":"",d->x,d->y);}
 printf("],\"edges\":[");
 for(int i=0;i<g->num_edges;i++){grid_edge *e=g->edges[i];printf("%s[%d,%d]",i?",":"",e->dot1->index,e->dot2->index);}
 printf("],\"faces\":[");
 for(int i=0;i<g->num_faces;i++){
  grid_face *f=g->faces[i];grid_find_incentre(f);
  printf("%s{\"vertices\":[",i?",":"");
  for(int j=0;j<f->order;j++)printf("%s%d",j?",":"",f->dots[j]->index);
  printf("],\"edges\":[");for(int j=0;j<f->order;j++)printf("%s%d",j?",":"",f->edges[j]->index);
  printf("],\"center\":[%d,%d],\"inradius\":%.9g}",f->ix,f->iy,f->iradius);
 }
 printf("],\"bounds\":[%d,%d,%d,%d],\"tile_size\":%d}\n",g->lowest_x,g->lowest_y,g->highest_x,g->highest_y,g->tilesize);
 grid_free(g);return 0;
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def run(args, timeout=25):
    result = subprocess.run([str(x) for x in args], text=True, capture_output=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f'command failed ({result.returncode}): {result.stderr[-2000:]}')
    return result.stdout


def parse_clues(description):
    """Loopy characters are single clues; uppercase A..Z encode 10..35."""
    out = []
    for ch in description:
        if '0' <= ch <= '9':
            out.append(int(ch))
        elif 'A' <= ch <= 'Z':
            out.append(ord(ch) - ord('A') + 10)
        elif 'a' <= ch <= 'z':
            out.extend([None] * (ord(ch) - ord('a') + 1))
        else:
            raise ValueError('invalid clue encoding')
    return out


def validate_graph(graph, clues):
    nodes, edges, faces = graph['nodes'], graph['edges'], graph['faces']
    if not nodes or not edges or not faces or len(faces) != len(clues):
        raise ValueError('empty graph or clue count mismatch')
    if any(len(p) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in nodes):
        raise ValueError('bad node coordinates')
    if len(set(map(tuple, nodes))) != len(nodes):
        raise ValueError('coincident node coordinates')
    seen, incidence = set(), [0] * len(edges)
    for edge in edges:
        if len(edge) != 2 or any(type(i) is not int or not 0 <= i < len(nodes) for i in edge) or edge[0] == edge[1]:
            raise ValueError('bad edge')
        key = tuple(sorted(edge))
        if key in seen:
            raise ValueError('duplicate edge')
        seen.add(key)
    for clue, face in zip(clues, faces):
        vs, es = face['vertices'], face['edges']
        if len(vs) < 3 or len(vs) != len(es) or len(set(vs)) != len(vs) or len(set(es)) != len(es):
            raise ValueError('bad face boundary')
        if any(type(v) is not int or not 0 <= v < len(nodes) for v in vs):
            raise ValueError('bad face vertex')
        if clue is not None and (type(clue) is not int or not 0 <= clue <= len(es)):
            raise ValueError('clue out of range')
        for i, edge_index in enumerate(es):
            if type(edge_index) is not int or not 0 <= edge_index < len(edges):
                raise ValueError('bad face edge index')
            if set(edges[edge_index]) != {vs[i], vs[(i + 1) % len(vs)]}:
                raise ValueError('face boundary disagrees with edge geometry')
            incidence[edge_index] += 1
    if any(n not in (1, 2) for n in incidence):
        raise ValueError('non-manifold or unused edge')


def verify(graph, clues, solution, source_project=None, timeout_ms=10000):
    """Answer SAT, then alternate edge assignment UNSAT; independent of Loopy."""
    validate_graph(graph, clues)
    if len(solution) != len(graph['edges']) or any(type(x) is not bool for x in solution):
        raise ValueError('solution must contain exactly one Boolean per edge')
    if source_project is not None:
        dependency = Path(source_project) / 'work/cspuz-deps/venv/lib/python3.12/site-packages'
        if str(dependency) not in sys.path:
            sys.path.insert(0, str(dependency))
    import z3 as Z
    solver = Z.Solver()
    solver.set(timeout=timeout_ms)
    variables = [Z.Bool(f'edge_{i}') for i in range(len(solution))]
    adj = [[] for _ in graph['nodes']]
    for i, (u, v) in enumerate(graph['edges']):
        adj[u].append((v, variables[i]))
        adj[v].append((u, variables[i]))
    active = []
    for links in adj:
        degree = Z.Sum([Z.If(e, 1, 0) for _, e in links])
        solver.add(Z.Or(degree == 0, degree == 2))
        active.append(degree == 2)
    # Every active vertex reaches one root along a strictly decreasing rank.
    # Degree 0/2 plus this connectivity constraint gives one nonempty loop.
    n = len(adj)
    root = Z.Int('loop_root')
    ranks = [Z.Int(f'rank_{i}') for i in range(n)]
    solver.add(root >= 0, root < n, Z.Or(active))
    for i, links in enumerate(adj):
        solver.add(ranks[i] >= 0, ranks[i] < n, Z.Implies(root == i, active[i]))
        solver.add(Z.Implies(active[i], Z.Or(root == i, *[
            Z.And(on, active[j], ranks[j] < ranks[i]) for j, on in links])))
    for clue, face in zip(clues, graph['faces']):
        if clue is not None:
            solver.add(Z.Sum([Z.If(variables[i], 1, 0) for i in face['edges']]) == clue)
    solver.push()
    solver.add(*[v == answer for v, answer in zip(variables, solution)])
    first = solver.check()
    solver.pop()
    second = None
    if first == Z.sat:
        solver.add(Z.Or([v != answer for v, answer in zip(variables, solution)]))
        second = solver.check()
    return {'rules_checked': first == Z.sat,
            'unique_verified': first == Z.sat and second == Z.unsat,
            'first_status': str(first), 'second_status': str(second),
            'checker': 'independent Z3 face counts, vertex degree 0/2, connected nonempty loop',
            'timeout_ms_per_check': timeout_ms, 'solution_projection': 'all graph edges'}


def generate(source_project, output_dir, params=None, seed='shape-honeycomb', timeout_seconds=30):
    if params is None:
        from shape_hex_cluster import generate as generate_cluster
        return generate_cluster(source_project, output_dir, seed=seed,
                                radius=3, timeout_seconds=timeout_seconds)
    source, out = Path(source_project).resolve(), Path(output_dir).resolve()
    match = re.fullmatch(r'(\d+)x(\d+)t(\d+)d([enh])', params)
    if params not in REVIEWED_PARAMS or not match:
        raise ValueError('reviewed exact variants only: 5x5t2dh, 5x5t1dh, 7x7t1dh')
    if source == out or source in out.parents:
        raise ValueError('output must be outside read-only source project')
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 120:
        raise ValueError('generation wall timeout must be 1..120 seconds')
    src = source / SOURCE_REL
    binary = source / 'work/paper-probe/build/loopy'
    library = source / 'work/paper-probe/build/libcore.a'
    prerequisites = [binary, library, src / 'grid.h', src / 'grid.c', src / 'loopy.c', src / 'LICENCE']
    if any(not p.is_file() for p in prerequisites):
        raise ValueError('missing native source/library/generator prerequisites')
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'request.json', {'params': params, 'seed': str(seed), 'source_project': str(source)})
    try:
        cfile, exporter = out / 'export_graph.c', out / 'export_graph'
        cfile.write_text(EXPORT_C)
        run(['cc', '-O2', '-std=c99', '-I', src, cfile, library, '-lm', '-o', exporter])
        raw = json.loads(run([binary, params, str(seed), '-'], timeout_seconds))
        if raw['params'] != params or not raw['description_valid']:
            raise ValueError('native generator did not preserve requested variant')
        save(out / 'native.json', raw)
        if '_' in raw['description']:
            grid_desc, clue_desc = raw['description'].split('_', 1)
        else:
            grid_desc, clue_desc = '', raw['description']
        graph = json.loads(run([exporter, match[3], match[1], match[2], grid_desc]))
        clues = parse_clues(clue_desc)
        pairs = re.findall(r'(\d+)([yn])', raw['solution_move'])
        if raw['solution_move'] != 'S' + ''.join(i + state for i, state in pairs):
            raise ValueError('unexpected native solution encoding')
        edge_answers = {int(i): state == 'y' for i, state in pairs}
        if len(edge_answers) != len(pairs) or set(edge_answers) != set(range(len(graph['edges']))):
            raise ValueError('native answer edge count/order mismatch')
        solution = [edge_answers[i] for i in range(len(graph['edges']))]
        evidence = verify(graph, clues, solution, source, min(10000, int(timeout_seconds * 1000)))
        save(out / 'verification.json', evidence)
        if not evidence['unique_verified']:
            raise ValueError('fresh independent correctness or uniqueness check failed')
        public = {'graph': graph, 'clues': clues, 'params': params, 'description': raw['description']}
        record = {'schema': 'shape-loopy-v1', 'type_id': 'slitherlink',
                  'shape': TYPES[int(match[3])], 'params': params, 'seed': str(seed),
                  'public_clues': public, 'solution': solution, 'validation': evidence,
                  'rules_zh': ['沿题面相邻顶点之间的边画线，形成一条闭合回路。',
                               '回路不能分叉、交叉，也不能形成多个圈。',
                               '数字表示该区域周围有几条边属于回路；空白区域无数量限制。'],
                  'difficulty': {'upstream': {'e': 'Easy', 'n': 'Normal', 'h': 'Hard'}[match[4]],
                                 'human_calibration': 'pending'},
                  'source': {'project': str(source), 'geometry': 'native grid_new exported from read-only libcore.a',
                             'license': 'MIT; upstream LICENCE SHA256 recorded',
                             'hashes': {str(p.relative_to(source)): sha(p) for p in prerequisites},
                             'exporter_source_sha256': sha(cfile)},
                  'scope': 'fresh verified instance; not annual production readiness'}
        save(out / 'public.json', public)
        save(out / 'record.json', record)
        return record
    except Exception as exc:
        save(out / 'failure.json', {'error': type(exc).__name__ + ': ' + str(exc)})
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-project', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--params', default=None,
                   help='Explicit native grid variant; omit for the default hexagonal honeycomb cluster')
    p.add_argument('--seed', default='shape-honeycomb')
    args = p.parse_args()
    result = generate(args.source_project, args.output_dir, args.params, args.seed)
    print(json.dumps({'record': str(Path(args.output_dir).resolve() / 'record.json'),
                      'shape': result['shape'], 'validation': result['validation']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
