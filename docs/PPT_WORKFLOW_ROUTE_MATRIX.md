# PPT And Workflow Route Matrix

This matrix separates Agent planning, generation services, foundation tools,
and Addon contributions. Each file-producing path has one execution owner.

## PPT routes

| Route | Entry | Execution owner | Boundary |
| --- | --- | --- | --- |
| Template generation | `web.tasks.template_library.TemplateLibrary._generate_pptx_from_template` | `app.core.services.ppt_generation_service.PPTGenerationService` | Template parameters remain separate from editor sessions. |
| File-task PPT creation/editing | Kernel file-task plan | `app.core.agent.toolkits.foundation` PPTX tools | Kernel selects admitted atomic tools; no workflow registry participates. |
| Existing PPT editing | Workspace open/save routes | `web.blueprints.workspace_assistant` plus `app.core.file.pptx_editor` | Session/save path, not presentation planning. |
| Generated PPT download | `GET /download/<session_id>` | `web.ppt_api_routes` and `web.ppt_session_manager` | Transport-only retrieval of an existing generated artifact. |

## Workflow ownership

- The retired `app.core.workflows` catalog/executor and workflow HTTP API must
  remain absent; free-form work is planned by the Kernel.
- `app.core.agent.toolkits.foundation` owns built-in file and office tools.
- `app.core.agent.addons` owns the controlled external-capability boundary.
- Addons may contribute tools, RAG, database, or API access through declared
  contracts; they do not become workflow owners implicitly.

## Acceptance

- No workflow catalog, executor registry, or workflow SSE route is reintroduced.
- Template PPT paths depend on the shared generation service.
- The foundation toolkit remains available independently of Addons.
- Addon capabilities cross the policy, permission, timeout, and audit boundary.
- No prompt-extension runtime participates in execution routing.
