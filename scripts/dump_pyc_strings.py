import marshal, sys
path = r"C:\Users\12524\Desktop\Koto\web\blueprints\__pycache__\editor_docs.cpython-311.pyc"
data = open(path, "rb").read()
code = marshal.loads(data[16:])

def walk(c, depth=0):
    for item in c.co_consts:
        if isinstance(item, str) and len(item) > 1:
            print(repr(item))
        elif hasattr(item, "co_consts"):
            walk(item, depth + 1)

walk(code)
