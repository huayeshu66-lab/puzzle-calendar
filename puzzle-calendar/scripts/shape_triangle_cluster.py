#!/usr/bin/env python3
"""Generate a fresh Loopy puzzle on a whole equilateral triangular board.

The n*n complete triangular faces are finalized before solution generation.
This generator never crops or reshapes an existing puzzle or its answer.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

sys.dont_write_bytecode = True
from shape_loopy import validate_graph, verify


def make_graph(side=6):
    if type(side) is not int or side not in (5, 6, 7):
        raise ValueError('side must be 5, 6 or 7')
    lattice = [(i, j) for j in range(side+1) for i in range(side-j+1)]
    node_ids = {p: k for k, p in enumerate(lattice)}
    height = math.sqrt(3)/2
    nodes = [[i+j/2, (side-j)*height] for i, j in lattice]
    edges, edge_ids, faces = [], {}, []

    def face(points):
        vs = [node_ids[p] for p in points]
        es = []
        for a, b in zip(vs, vs[1:]+vs[:1]):
            key = tuple(sorted((a, b)))
            if key not in edge_ids:
                edge_ids[key] = len(edges)
                edges.append(list(key))
            es.append(edge_ids[key])
        faces.append({'vertices': vs, 'edges': es,
                      'center': [sum(nodes[v][axis] for v in vs)/3 for axis in (0, 1)],
                      'inradius': math.sqrt(3)/6})

    for j in range(side):
        for i in range(side-j):
            face([(i, j), (i+1, j), (i, j+1)])
            if i+j <= side-2:
                face([(i+1, j), (i+1, j+1), (i, j+1)])
    graph = {'nodes': nodes, 'edges': edges, 'faces': faces,
             'bounds': [0, 0, side, side*height], 'tile_size': 1,
             'outline': 'equilateral-triangle', 'side': side,
             'lattice_nodes': [list(p) for p in lattice]}
    validate_graph(graph, [None]*len(faces))
    return graph


def incidence(graph):
    edge_faces = [[] for _ in graph['edges']]
    for i, face in enumerate(graph['faces']):
        for edge in face['edges']:
            edge_faces[edge].append(i)
    adjacent, exterior = [set() for _ in graph['faces']], set()
    for faces in edge_faces:
        if len(faces) == 1:
            exterior.add(faces[0])
        else:
            a, b = faces
            adjacent[a].add(b)
            adjacent[b].add(a)
    return edge_faces, adjacent, exterior


def connected(indices, adjacent, starts=None):
    if not indices:
        return True
    seen = set([min(indices)] if starts is None else starts) & indices
    todo = list(seen)
    while todo:
        for nxt in adjacent[todo.pop()] & indices - seen:
            seen.add(nxt)
            todo.append(nxt)
    return seen == indices


def simple_boundary(graph, edge_faces, selected):
    solution = [sum(face in selected for face in faces) == 1 for faces in edge_faces]
    degree = Counter(v for edge, on in zip(graph['edges'], solution) if on for v in edge)
    return solution if degree and set(degree.values()) == {2} else None


def candidate(graph, rng):
    edge_faces, adjacent, exterior = incidence(graph)
    count = len(graph['faces'])
    # Starting near the centre prevents a tiny corner loop dominating the page.
    cx, cy = graph['side']/2, graph['side']*math.sqrt(3)/3
    start = min(range(count), key=lambda i: sum((a-b)**2 for a, b in
                zip(graph['faces'][i]['center'], (cx, cy))))
    selected = {start}
    target = rng.randint(math.ceil(count*.45), math.floor(count*.72))
    while len(selected) < target:
        choices = sorted(set().union(*(adjacent[i] for i in selected))-selected)
        rng.shuffle(choices)
        for nxt in choices:
            trial = selected | {nxt}
            complement = set(range(count))-trial
            if (simple_boundary(graph, edge_faces, trial) is not None
                    and connected(complement, adjacent, complement & exterior)):
                selected = trial
                break
        else:
            return None
    solution = simple_boundary(graph, edge_faces, selected)
    if solution is None:
        return None
    interior = sum(on and len(faces) == 2 for on, faces in zip(solution, edge_faces))
    if interior < graph['side']*2 or interior < sum(solution)*.45:
        return None
    clues = [sum(solution[e] for e in face['edges']) for face in graph['faces']]
    return clues, solution, {'enclosed_faces': len(selected),
                            'loop_edges': sum(solution), 'interior_loop_edges': interior}


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def generate(source_project, output_dir, seed='equilateral-triangle', side=6,
             timeout_seconds=35):
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 40:
        raise ValueError('wall timeout must be 1..40 seconds')
    source, out = Path(source_project).resolve(), Path(output_dir).resolve()
    if source == out or source in out.parents:
        raise ValueError('output must be outside read-only source project')
    graph = make_graph(side)
    out.mkdir(parents=True, exist_ok=False)
    save(out/'request.json', {'seed': str(seed), 'side': side,
                             'source_project': str(source), 'timeout_seconds': timeout_seconds})
    started = time.monotonic()
    deadline = started+timeout_seconds

    def check(clues, solution, cap=1000):
        remaining = deadline-time.monotonic()-.4
        if remaining <= .1:
            raise TimeoutError('generation wall budget exhausted')
        return verify(graph, clues, solution, source,
                      max(1, min(cap, int(remaining*400))))

    try:
        rng, attempts = random.Random(str(seed)), 0
        while True:
            if time.monotonic() > deadline-.8:
                raise TimeoutError('no independently unique puzzle within wall budget')
            attempts += 1
            item = candidate(graph, rng)
            if item is None:
                continue
            clues, solution, metrics = item
            evidence = check(clues, solution)
            if evidence['unique_verified']:
                break
        order = list(range(len(clues)))
        rng.shuffle(order)
        removed = 0
        for i in order:
            if deadline-time.monotonic() < 1.2:
                break
            old, clues[i] = clues[i], None
            trial = check(clues, solution, cap=600)
            if trial['unique_verified']:
                removed += 1
                evidence = trial
            else:
                clues[i] = old
        evidence.update({'geometry': 'complete equilateral triangular face lattice',
                         'outline': 'equilateral-triangle', 'side': side,
                         'faces': len(clues), 'clues': len(clues)-removed,
                         'candidate_attempts': attempts, 'removed_clues': removed,
                         'wall_seconds': round(time.monotonic()-started, 3), **metrics})
        params = f'triangle-side{side}'
        public = {'graph': graph, 'clues': clues, 'params': params,
                  'outline': 'equilateral-triangle',
                  'description': ','.join('.' if c is None else str(c) for c in clues)}
        here, checker = Path(__file__).resolve(), Path(__file__).with_name('shape_loopy.py')
        record = {'schema': 'shape-loopy-v1', 'type_id': 'slitherlink',
                  'shape': 'triangular', 'outline': 'equilateral-triangle',
                  'params': params, 'seed': str(seed), 'public_clues': public,
                  'solution': solution, 'validation': evidence,
                  'rules_zh': ['沿题面相邻顶点之间的边画线，形成一条闭合回路。',
                               '回路不能分叉、交叉，也不能形成多个圈。',
                               '数字表示该三角形周围有几条边属于回路；空白区域无数量限制。'],
                  'difficulty': {'upstream': None, 'human_calibration': 'pending'},
                  'source': {'project': str(source),
                             'geometry': 'fresh equilateral triangular lattice; new loop and clues on finalized graph',
                             'dependency_scope': 'source project used only for installed Z3 dependency',
                             'hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in (here, checker)}},
                  'scope': 'fresh verified instance; difficulty and annual production uncalibrated'}
        save(out/'public.json', public)
        save(out/'record.json', record)
        save(out/'verification.json', evidence)
        return record
    except Exception as exc:
        save(out/'failure.json', {'error': f'{type(exc).__name__}: {exc}',
                                  'wall_seconds': round(time.monotonic()-started, 3)})
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-project', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--seed', default='equilateral-triangle')
    p.add_argument('--side', type=int, choices=(5, 6, 7), default=6)
    p.add_argument('--timeout-seconds', type=float, default=35)
    a = p.parse_args()
    result = generate(a.source_project, a.output_dir, a.seed, a.side, a.timeout_seconds)
    print(json.dumps({'record': str(Path(a.output_dir).resolve()/'record.json'),
                      'validation': result['validation']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
