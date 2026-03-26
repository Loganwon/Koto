"""Verify view-switching integration in the main page."""
import sys
sys.path.insert(0, '.')
from web.app import app

with app.test_client() as c:
    r = c.get('/')
    d = r.data.decode('utf-8')
    
    checks = {
        'Status 200': r.status_code == 200,
        'editorView present': 'id="editorView"' in d,
        'chatView present': 'id="chatView"' in d,
        'editorFrame iframe': 'id="editorFrame"' in d,
        'switchToEditorView JS': 'switchToEditorView' in d,
        'switchToChatView JS': 'switchToChatView' in d,
        'No old fileAssistantPanel': 'fileAssistantPanel' not in d,
        'No old fa-panel': 'fa-panel-iframe' not in d,
        'Sidebar navEditorBtn': 'navEditorBtn' in d,
        'data-view attribute': 'data-view' in d,
    }
    
    for name, ok in checks.items():
        print(f'  [{"PASS" if ok else "FAIL"}] {name}')
    
    if all(checks.values()):
        print('\nALL CHECKS PASSED')
    else:
        print('\nSOME CHECKS FAILED')
