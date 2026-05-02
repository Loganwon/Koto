#!/usr/bin/env python3
"""Inspect the exact JSON structure returned by parse_xlsx for Univer compatibility."""
import sys, json
sys.path.insert(0, '.')
from app.core.file.file_parser import parse_xlsx

result = parse_xlsx('workspace/Financial_Model_2026.xlsx')
print("=== TOP LEVEL KEYS ===")
print(list(result.keys()))

print("\n=== SHEETS ===")
sheets = result.get('sheets', {})
print(f"sheets type: {type(sheets)}, keys: {list(sheets.keys())[:5]}")

for sheet_id, sheet_data in list(sheets.items())[:1]:
    print(f"\n=== First Sheet: {sheet_id} ===")
    print(f"  sheetId: {sheet_data.get('id')!r}")
    print(f"  name: {sheet_data.get('name')!r}")
    print(f"  cellData type: {type(sheet_data.get('cellData'))!r}")
    cell_data = sheet_data.get('cellData', {})
    print(f"  cellData keys: {list(cell_data.keys())[:5]}")
    
    # Check first row
    first_row_key = list(cell_data.keys())[0] if cell_data else None
    if first_row_key:
        first_row = cell_data[first_row_key]
        print(f"  First row ({first_row_key!r}) type: {type(first_row).__name__}")
        print(f"  First row keys: {list(first_row.keys())[:5]}")
        first_cell_key = list(first_row.keys())[0]
        first_cell = first_row[first_cell_key]
        print(f"  First cell ({first_cell_key!r}): {first_cell!r}")

print("\n=== SERIALIZED JSON (first 2000 chars) ===")
json_str = json.dumps(result, ensure_ascii=False)
print(json_str[:2000])

print("\n=== SHEETS ORDER ===")
print(f"sheetOrder: {result.get('sheetOrder')}")

print("\n=== CHECKING _ensureWorkbookDefaults compatibility ===")
# Simulate what the frontend _ensureWorkbookDefaults does:
wb = result.copy()
if not wb.get('appVersion'): wb['appVersion'] = '0.5.0'
if not wb.get('locale'): wb['locale'] = 'zh-CN'
if wb.get('styles') is None: wb['styles'] = {}
if wb.get('resources') is None: wb['resources'] = []
print("After defaults:")
print(f"  appVersion: {wb.get('appVersion')!r}")
print(f"  locale: {wb.get('locale')!r}")
print(f"  styles: {wb.get('styles')!r}")
print(f"  resources: {wb.get('resources')!r}")
