#!/usr/bin/env python3
"""Create one A5 circular-maze calendar, answer and rules PDF.
Requires Python 3.11+, ReportLab and Node.js. No puzzle-publisher or external
solver project is used. Default text is English; --font enables Chinese labels.
"""
import argparse,datetime,json,shutil,subprocess,sys
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--date',default='2027-07-02')
 p.add_argument('--seed',type=int,default=20270103)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--font',type=Path,help='Optional embeddable Chinese TTF/TTC')
 p.add_argument('--skill-dir',type=Path,default=Path(__file__).resolve().parents[1]/'puzzle-calendar')
 p.add_argument('--node',default=shutil.which('node'))
 a=p.parse_args();d=datetime.date.fromisoformat(a.date);out=a.output.expanduser().resolve();skill=a.skill_dir.expanduser().resolve()
 if out.exists():p.error('Output directory already exists; choose a new one.')
 if not a.node:p.error('Node.js is required; install it or pass --node /path/to/node.')
 if not 0<a.seed<2**53:p.error('Seed must be a positive JavaScript-safe integer.')
 if skill==out or skill in out.parents:p.error('Output must be outside the skill directory.')
 from reportlab.pdfgen.canvas import Canvas
 from reportlab.pdfbase import pdfmetrics
 from reportlab.pdfbase.ttfonts import TTFont
 for f in [skill/'scripts/shape_circular.mjs',skill/'scripts/shape_boards.py',skill/'assets/WorkSans-Regular.ttf']:
  if not f.is_file():p.error('Missing skill file: '+str(f))
 pdfmetrics.registerFont(TTFont('Digits',str(skill/'assets/WorkSans-Regular.ttf')))
 chinese=a.font is not None
 if chinese:
  pdfmetrics.registerFont(TTFont('Labels',str(a.font.expanduser().resolve())))
  face=pdfmetrics.getFont('Labels').face
  required='年月日星期一二三四五六圆形迷宫随手记答案玩法从外圈箭头处进入沿通道走到中心不能穿墙虚线表示正确打印选择实际大小'
  if any(ord(ch) not in face.charToGlyph for ch in required):p.error('Selected font lacks Chinese glyphs.')
 else:pdfmetrics.registerFont(TTFont('Labels',str(skill/'assets/WorkSans-Regular.ttf')))
 # A separate raw-data directory preserves the independent maze proof.
 subprocess.run([a.node,str(skill/'scripts/shape_circular.mjs'),'--engine-dir',str(skill/'assets/codebox-maze'),'--output-dir',str(out/'production-private'),'--seed',str(a.seed),'--layers','7'],check=True,timeout=30,stdout=subprocess.DEVNULL)
 sys.path.insert(0,str(skill/'scripts'));from shape_boards import draw_circular
 raw=out/'production-private';public=json.loads((raw/'circular-puzzle.json').read_text());answer=json.loads((raw/'circular-answer.json').read_text());proof=json.loads((raw/'circular-proof.json').read_text())
 assert proof['unique_path'] and proof['independent_bfs_equals_engine_solver']
 mm=72/25.4;w,h=148*mm,210*mm
 def text(c,s,x,y,size=11,font='Labels'):
  if pdfmetrics.stringWidth(s,font,size)>124*mm:raise ValueError('Text exceeds A5 content width')
  c.setFillGray(.08);c.setFont(font,size);c.drawString(x*mm,h-y*mm,s)
 weekday=('星期'+'一二三四五六日'[d.weekday()]) if chinese else ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][d.weekday()]
 for solved,name in [(False,'calendar.pdf'),(True,'answer.pdf')]:
  c=Canvas(str(out/name),pagesize=(w,h),invariant=1,initialFontName='Labels');c.setTitle('Puzzle Calendar - '+str(d)+(' - Answer' if solved else ''))
  text(c,f'{d.day:02}',12,45,55,'Digits');text(c,f'{d.year} / {d.month:02}',52,31,15,'Digits');text(c,weekday,52,42,11)
  c.setStrokeGray(.25);c.setLineWidth(.5);c.line(12*mm,h-51*mm,136*mm,h-51*mm)
  text(c,('圆形迷宫' if chinese else 'Circular maze')+(' - '+('答案' if chinese else 'Answer') if solved else ''),12,62,13)
  draw_circular(c,answer if solved else public,(29*mm,50*mm,90*mm,90*mm),solved,style='medallion')
  text(c,('虚线表示正确通道。' if chinese else 'The dotted line shows the route.') if solved else ('随手记' if chinese else 'Notes'),12,178,10)
  if not solved:
   c.setStrokeGray(.75);c.setLineWidth(.3)
   for y in [186,194,202]:c.line(12*mm,h-y*mm,136*mm,h-y*mm)
  c.showPage();c.save()
 c=Canvas(str(out/'rules.pdf'),pagesize=(w,h),invariant=1,initialFontName='Labels');c.setTitle('Circular maze - Rules')
 text(c,'玩法' if chinese else 'How to play',12,32,23)
 rows=['从外圈箭头处进入，沿通道走到中心。','不能穿墙。','打印选择实际大小（100%）。'] if chinese else ['Enter through the opening marked by the arrow.','Follow the passages to the centre. Do not cross walls.','Print on A5 paper at actual size (100%).']
 for i,s in enumerate(rows):text(c,s,12,51+i*12,10)
 c.showPage();c.save()
 print(json.dumps({'date':str(d),'weekday':weekday,'output':str(out),'pdfs':['calendar.pdf','answer.pdf','rules.pdf'],'unique_path':True,'language':'zh' if chinese else 'en'},ensure_ascii=False))
if __name__=='__main__':main()
