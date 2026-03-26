from app.core.sandbox import run_python

r = run_python('print("hello sandbox"); print(2+2)')
print("stdout:", repr(r["stdout"]))
print("stderr:", repr(r["stderr"]))
print("error:", r["error"])
print("files:", list(r["files"].keys()))
