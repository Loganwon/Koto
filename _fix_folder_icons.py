path = r'web/static/js/app.js'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old1 = ('<div class="folder-item folder-item-computer" onclick="loadFolderDrives()">'
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px">'
        '<rect x="2" y="3" width="20" height="14" rx="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/>'
        '</svg><span>\u6211\u7684\u7535\u8111</span></div>')
new1 = ('<div class="folder-item folder-item-computer" onclick="loadFolderDrives()">'
        '<span style="font-size:15px;margin-right:6px">\U0001f5a5\ufe0f</span>'
        '<span>\u6211\u7684\u7535\u8111</span></div>')

old2 = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px;flex-shrink:0">'
        '<polyline points="15 18 9 12 15 6"></polyline></svg><span>..</span>')
new2 = '<span style="font-size:15px;margin-right:8px;flex-shrink:0">\u21a9</span><span>\u4e0a\u7ea7\u76ee\u5f55</span>'

c1 = old1 in content
c2 = old2 in content
print(f'old1 found: {c1}')
print(f'old2 found: {c2}')

if c1:
    content = content.replace(old1, new1, 1)
if c2:
    content = content.replace(old2, new2, 1)

if c1 or c2:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Written successfully')
else:
    print('Nothing to replace')
