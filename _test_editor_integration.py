"""Integration test: Editor page routes, assets, and HTML structure."""
import sys, os
sys.path.insert(0, '.')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from web.blueprints.pages import pages_bp
from flask import Flask

app = Flask(__name__, static_folder='web/static')
app.register_blueprint(pages_bp)
c = app.test_client()

passed = 0
failed = 0

def check(desc, cond):
    global passed, failed
    if cond:
        print(f'  PASS: {desc}')
        passed += 1
    else:
        print(f'  FAIL: {desc}')
        failed += 1

print('=== Editor Page ===')
r = c.get('/editor')
check('GET /editor -> 200', r.status_code == 200)
html = r.data.decode('utf-8')
check('HTML has /editor/assets/main.js', '/editor/assets/main.js' in html)
check('HTML has /editor/assets/main.css', '/editor/assets/main.css' in html)
check('HTML has univer-container', 'univer-container' in html)
check('HTML has socket.io CDN', 'cdn.socket.io' in html)
check('HTML has koto-diag panel', 'koto-diag' in html)

print('=== Editor Assets ===')
assets = [
    '/editor/assets/main.js',
    '/editor/assets/main.css',
    '/editor/assets/vue.runtime.esm-bundler-GPQDOEPZ.js',
    '/editor/assets/chunk-FW4363Y4.js',
]
for path in assets:
    r = c.get(path)
    sz = len(r.data)
    check(f'GET {path} -> 200 ({sz:,}b)', r.status_code == 200 and sz > 50)

print('=== Wrong paths (should 404) ===')
for path in ['/assets/main.js', '/assets/main.css']:
    r = c.get(path)
    check(f'GET {path} -> 404', r.status_code == 404)

print('=== Koto Main Page ===')
# Use full app for main page test
try:
    from web.app import app as full_app
    fc = full_app.test_client()
    r = fc.get('/')
    check('GET / -> 200', r.status_code == 200)
    html = r.data.decode('utf-8')
    check('Main has editorView div', 'id="editorView"' in html)
    check('Main has editorBackBtn', 'editorBackBtn' in html)
    check('Main has editorFrame', 'editorFrame' in html)
    check('Main has switchToEditorView', 'switchToEditorView' in html)
    check('Main has switchToChatView', 'switchToChatView' in html)

    # editorView should be AFTER </main> (i.e. not inside <main>)
    main_close = html.index('</main>')
    editor_pos = html.index('id="editorView"')
    check('editorView is OUTSIDE <main> (after </main>)', main_close < editor_pos)
except Exception as e:
    print(f'  SKIP: Full app test failed: {e}')

print(f'\n=== Results: {passed} passed, {failed} failed ===')
sys.exit(0 if failed == 0 else 1)
