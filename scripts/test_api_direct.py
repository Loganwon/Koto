#!/usr/bin/env python3
"""Direct API test for open_file endpoint."""
import sys, json, os, tempfile, shutil
sys.path.insert(0, '.')
sys.path.insert(0, 'web')

# Set up minimal Flask env
os.environ['TESTING'] = '1'

try:
    from web.blueprints.workspace_assistant import workspace_assistant_bp
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(workspace_assistant_bp)
    
    with app.test_client() as c:
        # Test XLSX open
        with open('workspace/Financial_Model_2026.xlsx', 'rb') as f:
            from io import BytesIO
            data = f.read()
        
        print("=== Testing XLSX open_file endpoint ===")
        response = c.post(
            '/api/v1/workspace/open_file',
            data={'file': (BytesIO(data), 'Financial_Model_2026.xlsx')},
            content_type='multipart/form-data'
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = json.loads(response.data)
            print(f"file_type: {result.get('file_type')}")
            print(f"file_name: {result.get('file_name')}")
            sheets = result.get('data', {}).get('sheets', {})
            print(f"sheets count: {len(sheets)}")
            for sid, sheet in list(sheets.items())[:1]:
                cd = sheet.get('cellData', {})
                print(f"sheet {sid!r}: {len(cd)} rows of cells")
                for rk, row in list(cd.items())[:1]:
                    for ck, cell in list(row.items())[:2]:
                        print(f"  cell[{rk}][{ck}] = {cell!r}")
        else:
            print(f"ERROR: {response.data.decode()[:300]}")

except ImportError as e:
    print(f"Import error: {e}")
    # Fallback: test the parser directly
    print("\n=== Fallback: test parse_xlsx directly ===")
    from app.core.file.file_parser import parse_xlsx
    result = parse_xlsx('workspace/Financial_Model_2026.xlsx')
    print(f"sheets: {list(result['sheets'].keys())}")
    for sid, sheet in list(result['sheets'].items())[:1]:
        cd = sheet.get('cellData', {})
        print(f"sheet {sid!r}: {len(cd)} rows of cells, first row: {list(list(cd.values())[0].keys())[:5]}")
