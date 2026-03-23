import re

with open('koto.spec', 'r', encoding='utf-8') as f:
    text = f.read()

# remove launcher dir addition
text = text.replace("_add(os.path.join(ROOT, 'launcher'),              'launcher')", "")

# make sure web is mapped correctly
if "'web'," not in text and "'web', " not in text:
    text = text.replace("'web.app',", "'web', 'web.app',")

with open('koto.spec', 'w', encoding='utf-8') as f:
    f.write(text)
