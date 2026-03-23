"""Quick audit: compare koto.spec hiddenimports vs actual disk modules."""
import os, re

ROOT = os.path.dirname(os.path.abspath(__file__))
spec = open(os.path.join(ROOT, 'koto.spec')).read()
hi_all = re.findall(r"'(web\.[^']+)'", spec)
hi_set = set(hi_all)

web_root = set()
for f in os.listdir(os.path.join(ROOT, 'web')):
    if f.endswith('.py') and f != '__init__.py':
        web_root.add('web.' + f[:-3])

web_bp = set()
for f in os.listdir(os.path.join(ROOT, 'web', 'blueprints')):
    if f.endswith('.py') and f != '__init__.py':
        web_bp.add('web.blueprints.' + f[:-3])

web_routes = set()
for f in os.listdir(os.path.join(ROOT, 'web', 'routes')):
    if f.endswith('.py') and f != '__init__.py':
        web_routes.add('web.routes.' + f[:-3])

disk_all = web_root | web_bp | web_routes | {'web.blueprints', 'web.routes'}

print('=== MISSING from hiddenimports (on disk but not listed) ===')
for m in sorted(disk_all - hi_set):
    print(' ', m)

print()
print('=== GHOST entries (in hiddenimports but NOT on disk) ===')
for m in sorted(hi_set - disk_all):
    print(' ', m)

# Check app/api .py files
print()
print('=== app/api modules on disk ===')
api_dir = os.path.join(ROOT, 'app', 'api')
for f in sorted(os.listdir(api_dir)):
    if f.endswith('.py') and f != '__init__.py':
        mod = 'app.api.' + f[:-3]
        flag = '  [MISSING]' if mod not in spec else ''
        print(f'  {mod}{flag}')
