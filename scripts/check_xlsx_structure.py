import sys, json
sys.path.insert(0, '.')
from app.core.file.file_parser import parse_xlsx

data = parse_xlsx('workspace/Financial_Model_2026.xlsx')

print('=== Top-level keys ===')
print(list(data.keys()))
print()
print('appVersion:', data.get('appVersion'))
print('locale:', data.get('locale'))
print('sheetOrder:', data.get('sheetOrder'))
print('styles keys (first 5):', list(data.get('styles', {}).keys())[:5])
print('resources:', data.get('resources'))
print()
print('=== Sheets ===')
for name, sheet in (data.get('sheets') or {}).items():
    print(f'\nSheet: {name}')
    print('  keys:', list(sheet.keys()))
    cd = sheet.get('cellData', {})
    print('  cellData rows:', list(cd.keys())[:5])
    if cd:
        first_row = list(cd.values())[0]
        print('  first row cols:', list(first_row.keys())[:5])
        if first_row:
            first_cell = list(first_row.values())[0]
            print('  first cell:', first_cell)
    config = sheet.get('config') or {}
    print('  config keys:', list(config.keys()))
    print('  rowCount:', sheet.get('rowCount'))
    print('  columnCount:', sheet.get('columnCount'))
    print('  id:', sheet.get('id'))
    print('  name:', sheet.get('name'))
