with open('web/static/vendor/univer/preset-sheets-core.umd.js', encoding='utf-8', errors='replace') as f:
    f.seek(0, 2)
    size = f.tell()
    f.seek(max(0, size-2000))
    tail = f.read(2000)
print('Last 2000 chars of preset-sheets-core.umd.js:')
print(tail[-1500:])
