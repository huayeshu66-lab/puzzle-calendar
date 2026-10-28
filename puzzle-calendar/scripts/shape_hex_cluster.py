#!/usr/bin/env python3
"""Make a fresh Loopy puzzle on a symmetric hexagonal cluster of hexagons.

Geometry is finalized before a new loop and clues are generated. This is not a
crop or decoration of a rectangular puzzle. Difficulty remains uncalibrated.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

sys.dont_write_bytecode = True
from shape_loopy import verify, validate_graph


def make_graph(radius=3):
    if type(radius) is not int or radius not in (2, 3):
        raise ValueError('radius must be 2 or 3')
    axial = [(q, r) for r in range(-radius, radius + 1)
             for q in range(-radius, radius + 1)
             if max(abs(q), abs(r), abs(q+r)) <= radius]
    offsets = [(1, 1), (0, 2), (-1, 1), (-1, -1), (0, -2), (1, -1)]
    node_ids, edge_ids, lattice, edges, faces = {}, {}, [], [], []
    for q, r in axial:
        vs, es = [], []
        for dx, dy in offsets:
            key = (2*q+r+dx, 3*r+dy)
            if key not in node_ids:
                node_ids[key] = len(lattice)
                lattice.append(key)
            vs.append(node_ids[key])
        for a, b in zip(vs, vs[1:]+vs[:1]):
            key = tuple(sorted((a, b)))
            if key not in edge_ids:
                edge_ids[key] = len(edges)
                edges.append(list(key))
            es.append(edge_ids[key])
        faces.append({'vertices': vs, 'edges': es,
                      'center': [math.sqrt(3)*(q+r/2), 1.5*r],
                      'inradius': math.sqrt(3)/2, 'axial': [q, r]})
    nodes = [[x*math.sqrt(3)/2, y/2] for x, y in lattice]
    xs, ys = zip(*nodes)
    graph = {'nodes': nodes, 'edges': edges, 'faces': faces,
             'bounds': [min(xs), min(ys), max(xs), max(ys)], 'tile_size': 2,
             'outline': 'hexagonal-cluster', 'radius': radius,
             'lattice_nodes': [list(x) for x in lattice]}
    validate_graph(graph, [None]*len(faces))
    return graph


def incidence(graph):
    edge_faces = [[] for _ in graph['edges']]
    for i, face in enumerate(graph['faces']):
        for e in face['edges']:
            edge_faces[e].append(i)
    adjacent = [set() for _ in graph['faces']]
    exterior = set()
    for fs in edge_faces:
        if len(fs) == 1:
            exterior.add(fs[0])
        else:
            a, b = fs
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


def candidate(graph, rng):
    edge_faces, adjacent, exterior = incidence(graph)
    count = len(graph['faces'])
    target = rng.randint(math.ceil(count*.40), math.floor(count*.70))
    center = next(i for i, f in enumerate(graph['faces']) if f['axial'] == [0, 0])
    selected = {center}
    while len(selected) < target:
        boundary = set().union(*(adjacent[i] for i in selected)) - selected
        selected.add(rng.choice(sorted(boundary)))
    complement = set(range(count)) - selected
    # All unselected regions must connect to the outside, preventing holes.
    if not connected(complement, adjacent, complement & exterior):
        return None
    solution = [sum(f in selected for f in fs) == 1 for fs in edge_faces]
    interior_edges = sum(on and len(fs) == 2 for on, fs in zip(solution, edge_faces))
    if interior_edges < 6 * graph['radius'] or interior_edges < sum(solution)*.4:
        return None
    clues = [sum(solution[e] for e in f['edges']) for f in graph['faces']]
    return clues, solution, {'enclosed_faces': len(selected),
                            'loop_edges': sum(solution), 'interior_loop_edges': interior_edges}


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def generate(source_project, output_dir, seed='hexagonal-honeycomb', radius=3,
             timeout_seconds=30):
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 120:
        raise ValueError('wall timeout must be 1..120 seconds')
    source, out = Path(source_project).resolve(), Path(output_dir).resolve()
    if source == out or source in out.parents:
        raise ValueError('output must be outside read-only source project')
    graph = make_graph(radius)
    out.mkdir(parents=True, exist_ok=False)
    save(out/'request.json', {'seed': str(seed), 'radius': radius,
                             'source_project': str(source), 'timeout_seconds': timeout_seconds})
    started = time.monotonic()
    deadline = started + timeout_seconds
    # Reserve enough of the budget to serialize a verified result, even if clue
    # reduction runs out of time. Solver timeouts never become uniqueness proof.
    def check(clues, solution, cap=1200):
        remaining = deadline - time.monotonic() - .3
        if remaining <= .1:
            raise TimeoutError('generation wall budget exhausted')
        # verify performs at most two solver calls; model construction is small.
        return verify(graph, clues, solution, source,
                      max(1, min(cap, int(remaining*400))))
    try:
        rng = random.Random(str(seed))
        attempts = 0
        while True:
            if time.monotonic() > deadline-.5:
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
            if deadline-time.monotonic() < 1:
                break
            old = clues[i]
            clues[i] = None
            trial = check(clues, solution, cap=700)
            if trial['unique_verified']:
                removed += 1
                evidence = trial
            else:
                clues[i] = old
        evidence.update({'geometry': 'axial symmetric hexagonal cluster',
                         'outline': 'hexagonal-cluster', 'radius': radius,
                         'faces': len(clues), 'clues': len(clues)-removed,
                         'candidate_attempts': attempts, 'removed_clues': removed,
                         'wall_seconds': round(time.monotonic()-started, 3), **metrics})
        params = f'hex-radius{radius}'
        public = {'graph': graph, 'clues': clues, 'params': params,
                  'outline': 'hexagonal-cluster',
                  'description': ','.join('.' if c is None else str(c) for c in clues)}
        here = Path(__file__).resolve()
        checker = here.with_name('shape_loopy.py')
        record = {'schema': 'shape-loopy-v1', 'type_id': 'slitherlink',
                  'shape': 'honeycomb', 'outline': 'hexagonal-cluster',
                  'params': params, 'seed': str(seed), 'public_clues': public,
                  'solution': solution, 'validation': evidence,
                  'rules_zh': ['沿题面相邻顶点之间的边画线，形成一条闭合回路。',
                               '回路不能分叉、交叉，也不能形成多个圈。',
                               '数字表示该六边形周围有几条边属于回路；空白区域无数量限制。'],
                  'difficulty': {'upstream': None, 'human_calibration': 'pending'},
                  'source': {'project': str(source),
                             'geometry': 'fresh axial hexagonal cluster; new loop and clues on finalized graph',
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
    p.add_argument('--seed', default='hexagonal-honeycomb')
    p.add_argument('--radius', type=int, choices=(2, 3), default=3)
    p.add_argument('--timeout-seconds', type=float, default=30)
    a = p.parse_args()
    result = generate(a.source_project, a.output_dir, a.seed, a.radius, a.timeout_seconds)
    print(json.dumps({'record': str(Path(a.output_dir).resolve()/'record.json'),
                      'validation': result['validation']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
