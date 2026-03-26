# Check Univer UMD global registration - inspect the UMD wrapper
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read(2000)
print(content[:2000])
