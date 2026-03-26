# Check beginning of preset-docs-core.umd.js and preset-sheets-core.umd.js
for name, path in [('docs', 'web/static/vendor/univer/preset-docs-core.umd.js'), ('sheets', 'web/static/vendor/univer/preset-sheets-core.umd.js')]:
    with open(path, encoding='utf-8', errors='replace') as f:
        head = f.read(1000)
    # also read last 1000
    with open(path, encoding='utf-8', errors='replace') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size-1000))
        tail = f.read(1000)
    print(f'=== {name}: HEAD ===')
    print(head[:600])
    print(f'=== {name}: TAIL ===')
    print(tail[-600:])
    print()
