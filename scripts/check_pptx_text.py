import sys
sys.path.insert(0, '.')
from app.core.file.file_parser import parse_pptx_geometry

data = parse_pptx_geometry('workspace/AI Agent.pptx')

# Show ALL shapes on slides 3, 4, 8, 9, 10 to understand TEXT vs TABLE
for slide_idx in [2, 3, 7, 8, 9]:
    slide = data['slides'][slide_idx]
    print(f'\n=== Slide {slide_idx+1} shapes ===')
    for s in slide['shapes']:
        t = s.get('_type', 'UNKNOWN')
        ht = s.get('has_text', False)
        paras = s.get('paragraphs', [])
        non_empty = [p for p in paras if any(r.get('text', '') for r in p.get('runs', []))]
        if t == 'TABLE':
            print(f'  id={s["id"]} _type={t} rows={s.get("table_rows")} cols={s.get("table_cols")} cells={len(s.get("cells",[]))}')
            for c in s.get('cells', [])[:5]:
                print(f'    cell[{c["row"]},{c["col"]}]: "{c["text"]}"')
        else:
            print(f'  id={s["id"]} _type={t} has_text={ht} non_empty_paras={len(non_empty)}')
            for p in non_empty:
                for r in p.get('runs', []):
                    if r.get('text'):
                        print(f'    -> "{r["text"]}"')
