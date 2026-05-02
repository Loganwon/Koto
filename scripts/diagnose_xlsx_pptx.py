#!/usr/bin/env python3
"""Diagnose xlsx/pptx loading issues."""
import sys
import json
sys.path.insert(0, '.')

from app.core.file.file_parser import parse_xlsx, parse_pptx_geometry

# ===== XLSX ANALYSIS =====
print("=== XLSX ANALYSIS ===")
r = parse_xlsx('workspace/Financial_Model_2026.xlsx')
sheets = r.get('sheets', {})
print('Top-level keys:', list(r.keys()))
print('appVersion:', r.get('appVersion'))
print('locale:', r.get('locale'))
print('sheetOrder:', r.get('sheetOrder'))

print()
print("=== CELL DATA JSON SERIALIZATION TEST ===")
sheet1 = list(sheets.values())[0]
cell_data = sheet1.get('cellData', {})
sample = {k: v for k, v in list(cell_data.items())[:2]}
json_str = json.dumps(sample)
print('Python dict:', repr(list(sample.items())[:1]))
print('JSON repr:', json_str[:300])
print()
print("BUG? Integer row/col keys become string keys in JSON: 0 -> '0'")
print("Univer Sheets IWorkbookData should use integer keys internally,")
print("but JSON always serializes object keys as strings.")

# Check the full workbook JSON
wb_json = json.dumps(r, ensure_ascii=False)
print()
print('Total JSON size:', len(wb_json), 'bytes')
print('First 500 chars of JSON:', wb_json[:500])

# ===== PPTX ANALYSIS =====
print()
print("=== PPTX ANALYSIS ===") 
r2 = parse_pptx_geometry('workspace/AI Agent.pptx')
slides = r2.get('slides', [])
print('Total slides:', len(slides))

for i, slide in enumerate(slides[:5]):
    shapes = slide.get('shapes', [])
    text_shapes = [s for s in shapes if s.get('has_text')]
    nonempty = []
    for s in text_shapes:
        all_text = ' '.join(
            run.get('text', '')
            for p in s.get('paragraphs', [])
            for run in p.get('runs', [])
        )
        if all_text.strip():
            nonempty.append((s, all_text))
    
    print(f'Slide {i}: {len(shapes)} shapes, {len(text_shapes)} text, {len(nonempty)} non-empty')
    for s, txt in nonempty[:2]:
        print(f'  shape={s["name"]!r} has_text={s.get("has_text")} text={txt[:80]!r}')
    
    # Check geometry
    for s in text_shapes[:2]:
        print(f'  geom: left={s.get("left")} top={s.get("top")} w={s.get("width")} h={s.get("height")}')

# Check slide 10 (the one with table in screenshot)
print()
print("=== SLIDE 10 DETAIL ===")
if len(slides) > 10:
    slide10 = slides[10]
    for s in slide10['shapes']:
        print(f'  type={s.get("_type")} name={s.get("name")!r} has_text={s.get("has_text")} '
              f'geom=({s.get("left")},{s.get("top")},{s.get("width")},{s.get("height")})')
        if s.get('paragraphs'):
            for p in s['paragraphs'][:2]:
                for run in p.get('runs', [])[:2]:
                    print(f'    run: {run!r}')
