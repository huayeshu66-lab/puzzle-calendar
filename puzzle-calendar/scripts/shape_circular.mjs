#!/usr/bin/env node
/** Adapt a trusted local MIT codebox/maze.js checkout to printable polar geometry.
 * No dependencies, network, installation, or hidden answer data in puzzle SVG.
 * Usage: node shape_circular.mjs --engine-dir DIR --output-dir DIR [--seed 20270103] [--layers 7]
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const argv = process.argv.slice(2), args = {};
const allowed = new Set(['--engine-dir','--output-dir','--seed','--layers']);
for(let i=0;i<argv.length;i+=2){
 const key=argv[i],value=argv[i+1];
 if(!allowed.has(key)) throw Error(`Unknown argument: ${key}`);
 if(Object.hasOwn(args,key)) throw Error(`Duplicate argument: ${key}`);
 if(value===undefined || value==='' || value.startsWith('--')) throw Error(`Missing value for ${key}`);
 args[key]=value;
}
if (!args['--engine-dir'] || !args['--output-dir']) throw Error('Required: --engine-dir and --output-dir (trusted local directories)');
const engine = await fs.realpath(path.resolve(args['--engine-dir']));
assert((await fs.stat(engine)).isDirectory(), 'engine-dir must be a trusted local directory');
const requestedOut=path.resolve(args['--output-dir']);
async function exists(p){try{await fs.lstat(p);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}}
async function futureRealpath(p){
 try{return await fs.realpath(p);}catch(e){
  if(e.code!=='ENOENT')throw e;
  const parent=path.dirname(p);if(parent===p)throw e;
  return path.join(await futureRealpath(parent),path.basename(p));
 }
}
if(await exists(requestedOut)) throw Error('output-dir already exists; choose a new directory');
const out=await futureRealpath(requestedOut), relativeToEngine=path.relative(engine,out);
if(relativeToEngine==='' || (!path.isAbsolute(relativeToEngine) && relativeToEngine!=='..' && !relativeToEngine.startsWith(`..${path.sep}`))) throw Error('output-dir must be outside engine-dir; engine source is read-only');
const seed = Number(args['--seed'] ?? 20270103), layers = Number(args['--layers'] ?? 7);
assert(Number.isSafeInteger(seed) && seed > 0, 'seed must be a positive integer');
assert(Number.isInteger(layers) && layers >= 3 && layers <= 12, 'layers must be 3..12');
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const license = await fs.readFile(path.join(engine,'LICENSE'),'utf8');
assert(license.includes('MIT License') && license.includes('Rob Dawson'), 'Expected official Codebox MIT source');
const engineFilesSha256={};
for(const name of ['maze.js','algorithms.js','random.js','utils.js','constants.js']) engineFilesSha256[name]=sha256(await fs.readFile(path.join(engine,name)));
if(await exists(path.join(engine,'package.json'))) engineFilesSha256['package.json']=sha256(await fs.readFile(path.join(engine,'package.json')));
const load = name => import(pathToFileURL(path.join(engine,name)));
const {buildCircularGrid} = await load('maze.js');
const {algorithms} = await load('algorithms.js');
const {buildRandom} = await load('random.js');
let strokes = [], colour = 'black';
const surface = {
 on(){}, setSpaceRequirements(){}, clear(){strokes=[];}, setColour(c){colour=c;},
 fillSegment(){}, convertCoords(x,y){return [x,y];},
 line(x1,y1,x2,y2){strokes.push({kind:'line',x1,y1,x2,y2,colour});},
 arc(cx,cy,r,start,end){strokes.push({kind:'arc',cx,cy,r,start,end,colour});}
};
const random = buildRandom(seed);
const grid = buildCircularGrid({layers,random,exitConfig:'hardest',drawingSurface:surface});
grid.initialise();
for (const _ of algorithms.recursiveBacktrack.fn(grid,{random})) {}
grid.placeExits();
const cells=[]; grid.forEachCell(c=>cells.push({id:c.id,coords:c.coords,links:c.links.map(n=>n.id),neighbours:c.neighbours.toArray().map(n=>n.id),start:!!c.metadata.startCell,end:!!c.metadata.endCell}));
const lookup = new Map(cells.map(c=>[c.id,c]));
const start=cells.find(c=>c.start), goal=cells.find(c=>c.end);
assert(start && goal && start.id !== goal.id);
const edges = new Set();
for(const c of cells) for(const n of c.links){
 assert(n !== c.id && lookup.has(n) && c.neighbours.includes(n));
 assert(lookup.get(n).links.includes(c.id));
 edges.add([c.id,n].sort().join('|'));
}
// Independent BFS, using only exported adjacency; no engine solver.
const queue=[start.id], parents=new Map([[start.id,null]]);
for(let i=0;i<queue.length;i++) for(const n of lookup.get(queue[i]).links) if(!parents.has(n)){parents.set(n,queue[i]);queue.push(n);}
assert.equal(parents.size,cells.length,'maze disconnected');
assert.equal(edges.size,cells.length-1,'maze not a tree / unique path not proven');
const answer=[]; for(let p=goal.id;p!==null;p=parents.get(p)) answer.push(p); answer.reverse();
for(let i=1;i<answer.length;i++) assert(lookup.get(answer[i-1]).links.includes(answer[i]));
grid.render();
// Remove identical overdrawn walls without altering their geometry.
const dedupe = items => [...new Map(items.map(s=>[JSON.stringify(s),s])).values()];
const walls=dedupe(strokes);
grid.findPathBetween(start.coords,goal.coords);
assert.deepEqual(grid.metadata.path.map(c=>c.join(',')),answer,'engine answer disagrees with independent BFS');
grid.render();
const solution=dedupe(strokes.filter(s=>s.colour!=='black'));
assert(solution.length>0 && walls.length>0);
const counts=Array.from({length:layers},(_,i)=>cells.filter(c=>c.coords[0]===i).length);
const polar=(r,a)=>[layers+r*Math.sin(a),layers-r*Math.cos(a)];
const mid = c=>c.coords[0]===0 ? [layers,layers] : polar(c.coords[0]+.5,(c.coords[1]+.5)*2*Math.PI/counts[c.coords[0]]);
const entranceAngle=(start.coords[1]+.5)*2*Math.PI/counts[layers-1];
const publicGeometry={schema:'circular-maze-geometry-v1',units:'grid units',coordinate_system:'x right, y down; arcs start at north, radians clockwise',size:2*layers,layers,counts,walls,start:{id:start.id,center:mid(start),opening:polar(layers,entranceAngle)},goal:{id:goal.id,center:mid(goal)},recommended_diameter_mm:76};
const answerGeometry={...publicGeometry,solution};
const n=v=>Number(v.toFixed(6));
function svgStroke(s){
 if(s.kind==='line')return `<line x1="${n(s.x1)}" y1="${n(s.y1)}" x2="${n(s.x2)}" y2="${n(s.y2)}"/>`;
 const p=a=>[s.cx+s.r*Math.sin(a),s.cy-s.r*Math.cos(a)];
 const a=p(s.start),b=p(s.end);return `<path d="M ${a.map(n).join(' ')} A ${n(s.r)} ${n(s.r)} 0 ${s.end-s.start>Math.PI?1:0} 1 ${b.map(n).join(' ')}"/>`;
}
function svg(solved){
 const marker=`<circle cx="${layers}" cy="${layers}" r="0.12" fill="#202020"/>`;
 const canvasMm=76*(2*layers+.3)/(2*layers);
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-0.15 -0.15 ${2*layers+.3} ${2*layers+.3}" width="${n(canvasMm)}mm" height="${n(canvasMm)}mm"><rect x="-.15" y="-.15" width="${2*layers+.3}" height="${2*layers+.3}" fill="white"/><g fill="none" stroke="#202020" stroke-width="0.033" stroke-linecap="round">${walls.map(svgStroke).join('')}</g>${solved?`<g fill="none" stroke="#555555" stroke-width="0.095" stroke-linecap="round">${solution.map(svgStroke).join('')}</g>`:''}${marker}</svg>\n`;
}
const fingerprint=createHash('sha256').update(JSON.stringify(cells.map(c=>[c.id,c.links.slice().sort()]))).digest('hex');
const proof={generator:'codebox/maze.js',engine_files_sha256:engineFilesSha256,license_sha256:sha256(license),algorithm:'recursiveBacktrack',seed,layers,cells:cells.length,edges:edges.size,visited:parents.size,connected:true,tree:true,unique_path:true,path_cells:answer.length,independent_bfs_equals_engine_solver:true,fingerprint,diameter_mm:76,radial_corridor_mm:76/(2*layers),minimum_noncentral_inner_arc_mm:Math.min(...counts.slice(1).map((c,i)=>(i+1)*2*Math.PI/c*76/(2*layers))),difficulty:'uncalibrated; form demonstration',physical_print_checked:false};
await fs.mkdir(path.dirname(out),{recursive:true});
// Exclusive final directory creation also prevents accidental overwrites after preflight.
await fs.mkdir(out);
for(const [name,value] of Object.entries({'circular-puzzle.json':publicGeometry,'circular-answer.json':answerGeometry,'circular-graph.json':{cells,start:start.id,goal:goal.id,answer},'circular-proof.json':proof})) await fs.writeFile(path.join(out,name),JSON.stringify(value,null,2)+'\n');
await fs.writeFile(path.join(out,'circular-puzzle.svg'),svg(false));
await fs.writeFile(path.join(out,'circular-answer.svg'),svg(true));
console.log(JSON.stringify({out,...proof},null,2));
