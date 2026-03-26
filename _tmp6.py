import re
files = {
    'preset-docs-core': 'web/static/vendor/univer/preset-docs-core.umd.js',
    'preset-sheets-core': 'web/static/vendor/univer/preset-sheets-core.umd.js',
    'preset-docs-core-zh-CN': 'web/static/vendor/univer/preset-docs-core-zh-CN.js',
    'preset-sheets-core-zh-CN': 'web/static/vendor/univer/preset-sheets-core-zh-CN.js',
}
pat = re.compile(r'i\.(\w+)=\{\}')
pat2 = re.compile(r'"UniverPreset\w+"')
for name, path in files.items():
    with open(path, encoding='utf-8', errors='replace') as f:
        content = f.read()
    hits = list(dict.fromkeys(pat.findall(content)))
    # look at last 500 chars for browser global registration
    tail = content[-800:]
    tail_hits = re.findall(r'[ie]\(([^)]{0,80})\)', tail)
    print(f'{name}:')
    print(f'  globals: {hits[:10]}')
    print(f'  tail: {tail[-300:]}')
    print()
