# Koto startup reliability contract

Koto desktop startup is independent from AI-provider readiness. The application
must open when no local model is installed, Ollama is stopped, a model drive is
detached, a configured model is missing or incompatible, or no cloud API key is
available.

## Blocking startup dependencies

Only failures that make the desktop shell fundamentally unusable may block
startup:

- the packaged Python/WebView runtime cannot load;
- required application files or core Python modules are missing;
- the Flask application cannot import or bind any local port;
- the desktop window process exits.

## Degraded capabilities

These conditions must be reported in the UI or detailed health endpoint and
must never terminate or restart the desktop process:

- Ollama is absent, stopped, slow, or outdated;
- a local model is missing, corrupt, detached, or version-incompatible;
- a cloud API key is absent, invalid, rate-limited, or offline;
- optional blueprints or background services are unavailable.

## Probe responsibilities

`/api/startup-health` proves only that the current Koto HTTP process can serve
the desktop. It must not contact providers, load model weights, inspect model
versions, or perform inference. `/api/health` and `/api/ping/models` may expose
detailed degraded state, but launchers must not use them as readiness gates.

The PowerShell launcher may retry a process that has exited. It must not kill a
still-running desktop process because a readiness deadline elapsed; the built-in
startup status page owns slow-start diagnostics and recovery.

Architecture tests in `tests/unit/test_startup_reliability_contract.py` enforce
these boundaries.

`/api/capabilities` is the configuration-only UI entry point. Its default form
must not perform network I/O. An explicit `?refresh=1` may inspect Ollama tags
and runtime compatibility, but still must not invoke generation or load model
weights. Public capability states are `available`, `unavailable`,
`misconfigured`, `incompatible`, and `checking`.

Normal desktop startup must not open the setup wizard. The wizard remains an
explicit repair action through the in-app banner/settings UI or the
`--setup`/`--reconfigure` command. The retired local routing model has no
desktop prewarm path; local capability probing remains an explicit settings or
`/api/capabilities?refresh=1` action and never loads model weights.

Both installer and portable release lanes must execute the shared eight-case
matrix: blank config, invalid cloud key, offline cloud endpoint, unselected
local model, stopped Ollama service, missing model tag, incompatible Ollama
runtime, and legacy-upgrade settings.
