#!/usr/bin/env python3
"""
Check if parse_xlsx output is valid for Univer Sheets by
testing against a known-good Univer data structure.
"""
import sys, json
sys.path.insert(0, '.')
from app.core.file.file_parser import parse_xlsx

# Parse the test file
result = parse_xlsx('workspace/Financial_Model_2026.xlsx')

# Verify all required Univer IWorkbookData fields
required_fields = ['id', 'name', 'appVersion', 'locale', 'styles', 'resources', 'sheetOrder', 'sheets']
print("=== REQUIRED FIELDS CHECK ===")
for field in required_fields:
    val = result.get(field)
    print(f"  {field!r}: {type(val).__name__} = {val!r if not isinstance(val, (dict, list)) else f'(len={len(val)})'}")

# Check sheets data
print("\n=== SHEETS STRUCTURE ===")
sheets = result.get('sheets', {})
for sheet_id, sheet in list(sheets.items())[:1]:
    print(f"  Sheet {sheet_id!r}:")
    for k in ['id', 'name', 'rowCount', 'columnCount']:
        print(f"    {k}: {sheet.get(k)!r}")
    cell_data = sheet.get('cellData', {})
    print(f"    cellData keys (type): {type(list(cell_data.keys())[0]).__name__}")
    
    # Verify cell structure
    for row_k, row in list(cell_data.items())[:2]:
        for col_k, cell in list(row.items())[:2]:
            print(f"    cell[{row_k!r}][{col_k!r}] = {cell!r}")

# Check JSON serialization
print("\n=== JSON SERIALIZE TEST ===")
try:
    json_str = json.dumps(result)
    print(f"JSON serialized OK, size: {len(json_str)} bytes")
    
    # Parse it back
    parsed = json.loads(json_str)
    
    # Check key types after JSON round-trip
    sheets_parsed = parsed.get('sheets', {})
    for sheet_id, sheet in list(sheets_parsed.items())[:1]:
        cell_data = sheet.get('cellData', {})
        for row_k, row in list(cell_data.items())[:1]:
            print(f"  After JSON round-trip: row key type={type(row_k).__name__!r}, value={row_k!r}")
            for col_k, cell in list(row.items())[:1]:
                print(f"  column key type={type(col_k).__name__!r}, value={col_k!r}")
                print(f"  cell structure: {cell!r}")
                # Check if s is inline style
                if 's' in cell:
                    s_val = cell['s']
                    print(f"  cell.s type={type(s_val).__name__!r}, valid_inline={'fs' in s_val or 'bl' in s_val if isinstance(s_val, dict) else False}")
except Exception as e:
    print(f"JSON ERROR: {e}")

# Simulate what Univer Sheets expects for a minimal test case
print("\n=== MINIMAL UNIVER TEST WORKBOOK ===")
min_wb = {
    "id": "test-wb-001",
    "name": "Test",
    "appVersion": "0.5.0",
    "locale": "zh-CN",
    "styles": {},
    "resources": [],
    "sheetOrder": ["sheet1"],
    "sheets": {
        "sheet1": {
            "id": "sheet1",
            "name": "Sheet1",
            "rowCount": 10,
            "columnCount": 10,
            "cellData": {
                "0": {
                    "0": {"v": "Hello", "t": 1},
                    "1": {"v": 42, "t": 2}
                }
            },
            "mergeData": []
        }
    }
}
print("Minimal workbook (no inline styles):", json.dumps(min_wb, indent=2)[:400])
print()
print("This is the baseline format that MUST work in Univer.")
print("Our parse_xlsx returns the same structure with optional 's' inline style objects.")
