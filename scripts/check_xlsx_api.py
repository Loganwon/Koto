import sys, json, urllib.request, urllib.parse, io, os

sys.path.insert(0, '.')

# Directly call the function rather than HTTP to avoid server issues
from app.core.file.file_parser import parse_xlsx
import json

data = parse_xlsx('workspace/Financial_Model_2026.xlsx')

# Simulate what the server returns
response = {
    "file_id": "test123",
    "file_type": "xlsx",
    "file_name": "Financial_Model_2026.xlsx",
    "data": data
}

# Save to file for inspection
with open('/tmp/xlsx_response.json', 'w', encoding='utf-8') as f:
    json.dump(response, f, ensure_ascii=False, indent=2)

print("Saved to /tmp/xlsx_response.json")
print("data keys:", list(data.keys()))
print("data['id']:", data.get('id'))
print("data['name']:", data.get('name'))
print()

# Check what _ensureWorkbookDefaults would do
# It does: Object.assign({ appVersion: '0.5.0', locale: 'zh-CN', styles: {}, resources: [] }, wb)
# Since data already has appVersion, locale, styles, resources - Object.assign would use data's values
print("After _ensureWorkbookDefaults (JS Object.assign adds defaults but data overrides):") 
print("  appVersion:", data.get('appVersion', '(missing)'))
print("  locale:", data.get('locale', '(missing)'))
print("  styles:", data.get('styles', '(missing)'))
print("  resources:", data.get('resources', '(missing)'))

# Check sheets format
print()
print("=== Sheet structure check for Univer compatibility ===")
for sheet_id, sheet_data in data['sheets'].items():
    print(f"Sheet '{sheet_id}' ({sheet_data.get('name', '?')}):")
    print(f"  Required fields: id={sheet_data.get('id')}, name={sheet_data.get('name')}")
    print(f"  rowCount={sheet_data.get('rowCount')}, columnCount={sheet_data.get('columnCount')}")
    cd = sheet_data.get('cellData', {})
    print(f"  cellData row count: {len(cd)}")
    print(f"  mergeData: {sheet_data.get('mergeData', [])}")
    # Check if config key is present
    if 'config' in sheet_data:
        print(f"  config: {sheet_data['config']}")
    else:
        print(f"  config: (not present)")
    break  # Just first sheet

print()
# Critical: does the JS 'data' key exist at top level? 
# The server returns json.data where data is IWorkbookData
# The frontend does: state.activeEditor.render(_ensureWorkbookDefaults(json.data))
# So json is {file_id, file_type, file_name, data: <IWorkbookData>}
# json.data IS the IWorkbookData
print("Top-level returned to frontend as json.data:", list(data.keys()))
