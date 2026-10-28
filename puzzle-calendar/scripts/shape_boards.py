#!/usr/bin/env python3
"""Vector drawing for verified shape specimens; no rectangular framing.

Coordinates passed by callers use PDF points. Rendering does not establish
uniqueness: callers must freshly verify the input through its matching engine.
"""
import math
import re


def draw_loop(canvas, record, box, font, answer=False, *, style='classic'):
    """Fit native Loopy geometry uniformly, preserving all nodes and face clues."""
    graph=record['public_clues']['graph']
    clues=record['public_clues']['clues']
    x,y,w,h=box
    x0,y0,x1,y1=graph['bounds']
    scale=min((w-4)/(x1-x0),(h-4)/(y1-y0))
    ox=x+(w-(x1-x0)*scale)/2
    oy=y+(h-(y1-y0)*scale)/2
    def p(i):
        xx,yy=graph['nodes'][i]
        return ox+(xx-x0)*scale,oy+(y1-yy)*scale
    if style not in ('classic','refined'):raise ValueError('Unknown loop style')
    incidence=[0]*len(graph['edges'])
    for face in graph['faces']:
        for edge in face['edges']:incidence[edge]+=1
    canvas.setStrokeColorRGB(.62,.62,.62)
    canvas.setLineWidth(.55)
    for i,(u,v) in enumerate(graph['edges']):
        if style=='refined':
            gray=.43 if incidence[i]==1 else .62
            canvas.setStrokeColorRGB(gray,gray,gray)
            canvas.setLineWidth(.8 if incidence[i]==1 else .55)
        canvas.line(*p(u),*p(v))
    if answer:
        canvas.setStrokeColorRGB(.06,.06,.06)
        canvas.setLineWidth(1.75)
        for selected,(u,v) in zip(record['solution'],graph['edges']):
            if selected:canvas.line(*p(u),*p(v))
    canvas.setFillColorRGB(.1,.1,.1)
    for i in range(len(graph['nodes'])):
        canvas.circle(*p(i),.8 if style=='refined' else .85,fill=1,stroke=0)
    # Native face incentres, not polygon bounding boxes, determine clue placement.
    font_size=min(13,min(f['inradius'] for f in graph['faces'])*scale*1.5)
    if font_size<10:raise ValueError('Clues too small in requested board area')
    canvas.setFont(font,font_size)
    for face,clue in zip(graph['faces'],clues):
        if clue is not None:
            xx,yy=face['center']
            canvas.drawCentredString(ox+(xx-x0)*scale,oy+(y1-yy)*scale-font_size*.34,str(clue))
    return {'kind':'loop','style':style,'shape':record['shape'],'edge_count':len(graph['edges']),
            'node_count':len(graph['nodes']),'clue_count':sum(c is not None for c in clues),
            'font_pt':font_size,'minimum_edge_mm':min(math.dist(graph['nodes'][u],graph['nodes'][v]) for u,v in graph['edges'])*scale*25.4/72,
            'outer_frame':False}


def bridge_public(raw):
    m=re.match(r'(\d+)x(\d+)',raw['params'])
    if not m:raise ValueError('Unrecognised bridge dimensions')
    width,height=map(int,m.groups())
    cells=[]
    for char in raw['description']:
        if char.isdigit():cells.append(int(char))
        elif 'a'<=char<='z':cells.extend([None]*(ord(char)-96))
        else:raise ValueError('Unrecognised bridge clue encoding')
    if len(cells)!=width*height:raise ValueError('Bridge clue dimensions differ')
    return width,height,[(i%width,i//width,n) for i,n in enumerate(cells) if n is not None]


def draw_bridges(canvas, record, box, font, answer=False, *, style='classic'):
    """Keep island coordinates; omit only the non-semantic surrounding frame."""
    width,height,islands=bridge_public(record['raw'])
    x,y,w,h=box
    if style not in ('classic','black-islands'):raise ValueError('Unknown bridge style')
    base_radius=7.6
    radius=8.5 if style=='black-islands' else base_radius
    # The black-island treatment preserves the baseline island centers exactly.
    step=min((w-2*base_radius-4)/(width-1),(h-2*base_radius-4)/(height-1))
    if step*25.4/72<7:raise ValueError('Bridge spacing too small')
    ox=x+(w-(width-1)*step)/2
    oy=y+(h-(height-1)*step)/2
    def p(xx,yy):return ox+xx*step,oy+(height-1-yy)*step
    if answer:
        canvas.setStrokeColorRGB(.1,.1,.1)
        canvas.setLineWidth(.9)
        for a,b,c,d,n in re.findall(r'L(\d+),(\d+),(\d+),(\d+),([12])',record['raw']['solution_move']):
            a,b,c,d,n=map(int,(a,b,c,d,n))
            ax,ay=p(a,b);bx,by=p(c,d)
            for offset in ([0] if n==1 else [-1.3,1.3]):
                canvas.line(ax+(offset if a==c else 0),ay+(offset if b==d else 0),
                            bx+(offset if a==c else 0),by+(offset if b==d else 0))
    font_size=12.5 if style=='black-islands' else 12
    canvas.setFont(font,font_size)
    canvas.setLineWidth(.9)
    for xx,yy,n in islands:
        cx,cy=p(xx,yy)
        fill=.10 if style=='black-islands' else 1
        canvas.setFillColorRGB(fill,fill,fill)
        canvas.setStrokeColorRGB(.1,.1,.1)
        canvas.circle(cx,cy,radius,fill=1,stroke=1)
        ink=1 if style=='black-islands' else .1
        canvas.setFillColorRGB(ink,ink,ink)
        canvas.drawCentredString(cx,cy-(font_size*.34 if style=='black-islands' else 4),str(n))
    return {'kind':'bridges','style':style,'islands':len(islands),'font_pt':font_size,
            'spacing_mm':step*25.4/72,'minimum_node_clearance_mm':(step-2*radius-.9)*25.4/72,
            'island_centers_preserved':True,'outer_frame':False}


def draw_circular(canvas, geometry, box, answer=False, *, style='classic'):
    """Draw native circular cell walls and curved solution passages."""
    x,y,w,h=box
    scale=min(w,h)/geometry['size']
    ox=x+(w-geometry['size']*scale)/2
    oy=y+(h-geometry['size']*scale)/2
    if style not in ('classic','medallion'):raise ValueError('Unknown maze style')
    grid_center=geometry['size']/2
    opening=geometry['start']['opening']
    rotation=math.pi-math.atan2(opening[0]-grid_center,grid_center-opening[1]) if style=='medallion' else 0
    cs,sn=math.cos(rotation),math.sin(rotation)
    def point(xx,yy):
        dx,dy=xx-grid_center,yy-grid_center
        xx,yy=grid_center+cs*dx-sn*dy,grid_center+sn*dx+cs*dy
        return ox+xx*scale,oy+(geometry['size']-yy)*scale
    def segment(s):
        if s['kind']=='line':
            canvas.line(*point(s['x1'],s['y1']),*point(s['x2'],s['y2']))
        elif s['kind']=='arc':
            cx,cy=point(s['cx'],s['cy']);r=s['r']*scale
            canvas.arc(cx-r,cy-r,cx+r,cy+r,90-math.degrees(s['start']+rotation),-math.degrees(s['end']-s['start']))
        else:raise ValueError('Unknown maze segment')
    canvas.setStrokeColorRGB(.18,.18,.18)
    canvas.setLineWidth(.75)
    if style=='medallion':
        canvas.setLineCap(1);canvas.setLineJoin(1)
    for s in geometry['walls']:
        if style=='medallion':
            canvas.setLineWidth(1.25 if s['kind']=='arc' and abs(s['r']-grid_center)<1e-8 else .8)
        segment(s)
    if answer:
        if not geometry.get('solution'):raise ValueError('Maze answer geometry absent')
        canvas.setStrokeColorRGB(.1,.1,.1)
        canvas.setLineWidth(1.3)
        canvas.setDash(2,1.4)
        canvas.line(*point(*geometry['start']['opening']),*point(*geometry['start']['center']))
        for s in geometry['solution']:segment(s)
        canvas.setDash()
    # Small outward triangle indicates the sole entry; center target is meaningful.
    a=geometry['start']['opening'];cx,cy=point(*a)
    center=point(*geometry['goal']['center'])
    vx,vy=cx-center[0],cy-center[1]
    norm=math.hypot(vx,vy);vx/=norm;vy/=norm
    canvas.setFillColorRGB(.15,.15,.15)
    path=canvas.beginPath();path.moveTo(cx+vx*2,cy+vy*2)
    path.lineTo(cx+vx*7-vy*2.3,cy+vy*7+vx*2.3)
    path.lineTo(cx+vx*7+vy*2.3,cy+vy*7-vx*2.3)
    path.close();canvas.drawPath(path,fill=1,stroke=0)
    canvas.setLineWidth(.7)
    if style=='medallion':
        canvas.circle(*center,4.4,fill=1,stroke=0)
        canvas.setFillColorRGB(1,1,1);canvas.circle(*center,1.35,fill=1,stroke=0)
    else:canvas.circle(*center,2.0,fill=0,stroke=1)
    return {'kind':'circular-maze','style':style,'rotation_radians':rotation,'walls':len(geometry['walls']),
            'diameter_mm':geometry['size']*scale*25.4/72,'outer_frame':'circular maze boundary with entry opening'}
