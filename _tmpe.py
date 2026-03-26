import re
for filename, path in [('docs-core', 'web/static/vendor/univer/preset-docs-core.umd.js'), ('sheets-core', 'web/static/vendor/univer/preset-sheets-core.umd.js')]:
    with open(path, encoding='utf-8', errors='replace') as f:
        content = f.read()
    pat = re.compile(r'[A-Za-z_\$]\.([A-Z][A-Za-z0-9]+)=\{\}')
    all_g = sorted(set(pat.findall(content)))
    print(f'{filename} registers: {all_g}')
