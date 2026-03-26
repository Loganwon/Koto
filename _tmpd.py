import re
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find ALL var.SomeCamelName={} to get all globals
pat = re.compile(r'[A-Za-z_\$]\.([A-Z][A-Za-z0-9]+)=\{\}')
all_globals = sorted(set(pat.findall(content)))
print(f'All {len(all_globals)} globals in presets bundle:')
for g in all_globals:
    print(' ', g)
