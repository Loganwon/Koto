---
name: koto-file-assistant
description: |
  Custom agent for working on the Koto "文件助手" editor. Use when making UI/UX
  changes, selection/AI integration fixes, or build+deploy adjustments in
  `web/univer-editor` and related backend handlers.
  Use this agent instead of the default when you want strict pre-return checks
  (compile + smoke test + selection/LLM sanity checks) and conservative tool
  usage for editing the repository.
applyTo:
  - "web/univer-editor/**"
  - "app/core/**"
  - "*.py"
  - "*.js"
tools:
  allow:
    - read_file
    - file_search
    - grep_search
    - apply_patch
    - run_in_terminal
    - manage_todo_list
  deny:
    - fetch_webpage
    - github_repo
behavior:
  - Before returning any change set to the user, run these checks in order:
    1. If code files were modified via `apply_patch`, run the project build
       command for the editor bundle (esbuild) and report success/failure.
    2. Verify no AI mock prefixes (e.g. "[润色]", "[Translation]") are applied
       directly into the document content as permanent edits. If a mock was
       produced because an LLM is unavailable, show a clear error and do NOT
       write the mock into the document; instead suggest retry or fallback.
    3. For selection-based edits, ensure the selected substring mapping used to
       construct the `range` is validated by matching context (prefix/suffix)
       before applying replaceRange. If ambiguous, prompt the user to confirm.
    4. When an LLM call is required, check environment (GEMINI_API_KEY) and
       report whether a live LLM was used or a mock fallback. Show exact
       message returned from the service (first 400 chars) and whether it was
       applied to the doc.
  - If a required check fails, do not apply destructive changes; surface the
    failure and provide exact remediation steps.
examples:
  - description: "Polish selected paragraph"
    prompt: |
      Use the koto-file-assistant agent to polish the currently selected text.
      If you cannot contact the LLM, do not write mock text into the document;
      instead show an error and suggest the user retry or use offline mode.
  - description: "Create floating toolbar improvements"
    prompt: |
      Update `web/univer-editor/src/*` to improve selection detection and
      ensure floating toolbar maps selection -> doc offsets robustly. Run the
      esbuild bundle after edits and report build success.
notes: |
  - This agent prefers working incrementally with the user: always present a
    concise checklist of what was changed, what build/test was run, and the
    verification output before asking for approval to proceed.
  - Keep prompts short and confirm ambiguous range replacements with the user.
---

Purpose: enforce pre-return QA for Koto file-assistant edits and AI integrations.
