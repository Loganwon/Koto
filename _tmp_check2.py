import re
files = [
    ('presets.umd.js', 'web/static/vendor/univer/presets.umd.js'),
    ('preset-docs-core.umd.js', 'web/static/vendor/univer/preset-docs-core.umd.js'),
]
for name, path in files:
    with open(path, encoding='utf-8', errors='replace') as f:
        content = f.read()
    # Search for UMD factory registration patterns
    # Look for typical patterns: define/require/exports/root
    patterns = [
        re.compile(r'exports\["([^"]+)"\]'),
        re.compile(r'root\[\"?([A-Z][A-Za-z]+)\"?\]'),
        re.compile(r'globalThis\[\"([^\"]+)\"\]'),
        re.compile(r'e\.([A-Za-z_\$][A-Za-z0-9_\$]+)\s*=\s*\w+\.[A-Z]'),
    ]
    print(f'--- {name} ({len(content)} bytes) ---')
    # Look near start and end for UMD wrapper
    for chunk_name, chunk in [('start', content[:500]), ('end', content[-500:])]:
        if any(c.isalpha() for c in chunk):
            print(f'  {chunk_name}:', chunk[:200])
    for pat in patterns:
        hits = pat.findall(content[:5000])
        if hits:
            print(f'  matches:', hits[:5])
    print()
