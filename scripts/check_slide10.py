#!/usr/bin/env python3
"""Check backend table parsing for slide 10."""
import sys, json
sys.path.insert(0, '.')
from app.core.file.file_parser import parse_pptx_geometry
result = parse_pptx_geometry('workspace/AI Agent.pptx')
slides = result['slides']
# Check slide 10 (index 9) specifically
slide = slides[9]
print(f'Slide 10: {len(slide["shapes"])} shapes')
for sh in slide['shapes']:
    print(f'  Shape id={sh["id"]}, _type={sh.get("_type")}, name={sh.get("name")!r}')
    if sh.get('_type') == 'TABLE':
        print(f'    table_rows={sh.get("table_rows")}, table_cols={sh.get("table_cols")}')
        cells = sh.get('cells', [])
        print(f'    cells: {json.dumps(cells[:5], ensure_ascii=False)}')
    elif sh.get('has_text'):
        paras = sh.get('paragraphs', [])
        text = ' '.join(r.get('text','') for p in paras for r in p.get('runs',[]))
        print(f'    text: {text[:80]!r}')
