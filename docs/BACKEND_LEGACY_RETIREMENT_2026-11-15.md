# Backend legacy retirement audit

This batch removes five disconnected implementations from the current standalone
workspace. It preserves the Kernel, ToolCatalog, TaskLedger, file-task and DOCX
runtime, current frontend, packaging configuration, and Office/WPS adapters.

## Retired implementations and reference evidence

| Deleted source | Evidence before removal | Active behavior retained |
| --- | --- | --- |
| `web/code_generator.py` | Only `TestCodeGenerator` and `TestCodeTemplate` in `test_web_modules_batch10.py` imported it. No route, tool, script, host or configuration reference. Its natural-language generation method returned placeholder code. Its `__main__` was an isolated demonstration. | Existing Kernel/model and registered execution tools; no production import needed replacement. |
| `web/files/filegen_time_context.py` | Only date-parsing coverage tests imported it; `web.files` did not export it. No production or script caller. | Stable chat system instruction and model interpretation; no disconnected keyword time injector. |
| `app/core/services/feedback_loop.py` | Only `TestFeedbackLoopManager` imported this old separate model-rewrite loop. Its evaluator dependency was the retired evaluator below. | Existing Kernel feedback, validation and retry behavior. |
| `app/core/services/quality_evaluator.py` | Referenced only by the disconnected feedback loop and `TestQualityEvaluator`. | Active file-task quality and completion checks remain unchanged. |
| `app/core/services/search_service.py` | Only `TestSearchService` imported it. The compatibility method already returned a fixed retired-grounding failure. | Registered search plugin through `web_search_gateway`; no production import needed replacement. |

The audit inspected Python imports and module/class strings in `app`, `web`,
`launcher`, `src`, `companion`, and `scripts`, plus tracked non-Python
configuration/packaging references. The package initializers did not expose the
retired helpers. `koto.spec` discovers source files dynamically and had no
hardcoded dependency on these modules; no build-file edit was needed.

The 52 direct tests that existed solely for these retired implementations were
removed from their six mixed coverage files; unrelated tests were preserved.
The existing package-integrity retirement lists now include these paths. Older
architecture prohibitions against reintroducing root shims and keyword routing
remain in place.

## Validation

- Post-removal scan found no references to the retired modules or classes in
  production, host adapters, or scripts.
- A fresh venv Python process returned `None` from `importlib.util.find_spec`
  for all five retired module paths, confirming no compiled fallback remained
  discoverable in source mode.
- 624 tests passed across package integrity, architecture guardrails, Agent
  context, active search boundary, editor code execution, and the six affected
  coverage modules. Evidence: `build/backend-legacy-retirement.xml`.

## Deferred findings and limits

`image_manager.py`, the isolated `doc_gen_service` helper group, the separately
implemented `web.audit_logger`, and several classes exported by the document
and file package initializers remain audit candidates. They were not removed
in this bounded batch. Active document conversion, search backend, batch file
operations and work-file-library paths remain intact.

The repository scan cannot account for undocumented external Python consumers.
Existing release packages are unchanged; source retirement takes effect in a
new build. This batch performs no Git staging, commit, push, configuration
change, or user-data cleanup.
