import re
files = [
    ('presets.umd.js', 'web/static/vendor/univer/presets.umd.js'),
    ('preset-docs-core.umd.js', 'web/static/vendor/univer/preset-docs-core.umd.js'),
    ('preset-sheets-core.umd.js', 'web/static/vendor/univer/preset-sheets-core.umd.js'),
    ('preset-docs-core-zh-CN.js', 'web/static/vendor/univer/preset-docs-core-zh-CN.js'),
    ('preset-sheets-core-zh-CN.js', 'web/static/vendor/univer/preset-sheets-core-zh-CN.js'),
]
pat = re.compile(r'(root|globalThis)\[\"([^\"]+)\"\]')
for name, path in files:
    with open(path, encoding='utf-8', errors='replace') as f:
        content = f.read(10000)
    hits = pat.findall(content)
    print(name, '->', hits[:8])
