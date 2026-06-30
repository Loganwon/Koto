# Python Test Environment

Updated: 2026-06-08

Koto's local test entrypoint is the default `python` on this machine:

```powershell
python -m pytest
```

Current default interpreter:

```text
C:\Users\12524\anaconda3\python.exe
```

Required file-task packages now available in that environment:

- `pytest`
- `python-docx`
- `openpyxl`
- `lxml`
- `Pillow`
- `matplotlib`
- `requests`

`python-docx 1.2.0` was copied from the bundled Koto runtime into the Anaconda
site-packages because the default pytest environment previously lacked `docx`.

Financial chart generation sets `MPLCONFIGDIR` to a writable task artifact
directory before importing matplotlib. This avoids permission failures on
`C:\Users\12524\.matplotlib\fontlist-*.json.matplotlib-lock`.
