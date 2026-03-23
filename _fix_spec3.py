import re

with open('koto.spec', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("'web.app',", "'web', 'web.app',")

with open('koto.spec', 'w', encoding='utf-8') as f:
    f.write(text)
