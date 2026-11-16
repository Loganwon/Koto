# Koto Addon Integration

Addon is Koto's controlled external-capability layer. It contributes tools or
retrievers to the Agent; it does not own planning, the execution loop, memory,
or final-answer validation.

Database, enterprise knowledge, lineage, field policy, and Live Database
product architecture are specified in
[`INFORMATION_MANAGEMENT_SYSTEM.md`](INFORMATION_MANAGEMENT_SYSTEM.md). Data
Addons use that host layer; they must not each invent a separate authorization,
masking, or audit implementation.

## Runtime flow

1. `POST /api/plugin-protocol/validate` validates a versioned manifest.
2. `POST /api/plugin-protocol/registrations` stores the manifest, explicit task
   bindings, permission grants, non-secret config, and secret references. New
   registrations are always disabled.
3. A trusted host module registers executable code with
   `register_addon_factory(addon_id, factory)`. HTTP requests cannot register a
   factory. Operators may load factory modules through the
   `KOTO_ADDON_BOOTSTRAP_MODULES` allowlist.
4. Enabling a registration rebuilds the Addon runtime and runs manifest,
   permission, dependency, schema, limit, transport, secret, and health checks.
5. For each task, `AddonRuntime.plan()` selects contributions using task type,
   intent patterns, file types, capability requirements, data classification,
   and read-only requirements.
6. Only tool names selected by that plan are added to the current Agent's tool
   registry. Other admitted Addon tools are not visible to the model.
7. Database Tool contributions must set `requires_invocation_context=True`.
   The Kernel injects `AddonInvocationContext` outside model arguments; missing,
   invalid, or model-forged context is rejected and audited before the handler runs.
8. Retriever contributions execute only with a host-verified tenant and
   principal. Evidence is injected as cited data, never as system instructions.

## Governed database Tool contract

`invocation_context` is a reserved handler argument and must never appear in the
manifest input schema. The model can supply only business parameters:

```python
def customer_lookup(*, invocation_context, customer_id):
    invocation_context.require_identity()
    return governed_gateway.lookup(
        tenant_id=invocation_context.tenant_id,
        principal_id=invocation_context.principal_id,
        purpose_code=invocation_context.purpose_code,
        customer_id=customer_id,
    )

ToolSpec(
    name="customer_lookup",
    description="Look up a governed customer profile.",
    input_schema={
        "type": "object",
        "properties": {"customer_id": {"type": "string"}},
        "required": ["customer_id"],
        "additionalProperties": False,
    },
    handler=customer_lookup,
    source="plugin:com.example.customer",
    read_only=True,
    requires_invocation_context=True,
)
```

The host derives tenant and principal from the authenticated request and owns the
purpose code. Addon registration data, user prompts, model tool arguments, and
client JSON cannot override this context.

## Persisted registration

`config/addons.json` contains declarative data only:

```json
{
  "manifest": { "plugin_id": "com.example.knowledge" },
  "bindings": [
    {
      "contribution_name": "knowledge_lookup",
      "task_types": ["CHAT", "RESEARCH"],
      "intent_patterns": ["知识库", "历史资料"],
      "file_types": [],
      "priority": 70
    }
  ],
  "granted_permissions": ["database.read"],
  "config": {},
  "secret_bindings": { "api_key": "env:EXAMPLE_API_KEY" },
  "enabled": false
}
```

Secret values must stay in the host secret store or environment. The registry
stores only references. Registration does not import or execute package code.

## Ownership

- `app.core.agent.addons.store`: durable declarative registrations.
- `app.core.agent.addons.bootstrap`: trusted factories and runtime refresh.
- `app.core.agent.addons.runtime`: admission, planning, tools, and retrieval.
- `app.core.agent.plugin_protocol`: manifest, lifecycle, permission, data, and
  evidence contracts.
- `app.core.agent.tool_profiles`: per-task composition of planned Addon tools.
- `web.services.chat_stream.orchestrator`: task planning and identity-bound RAG.
- `/addons`: validation, registration, status, and enable/disable UI.

HTTP and MCP remain valid protocol-schema transport values for forward
compatibility, but the current runtime enables only `in_process`. Registrations
using a schema-only transport remain `blocked`; Koto never silently falls back
to arbitrary imports, endpoints, MCP injection, or user scripts.

## Isolation from host tools

The production Agent has exactly one named tool profile: `core`. It combines a
reviewed allowlist of host-owned built-ins with only the Addon tools selected by
the current task plan. Legacy `full`/`light` switches have been removed. The
standalone MCP service and user-tool loader are not Agent extension paths.

Host-owned implementations live under `app.core.agent.toolkits`; the retired
`app.core.agent.plugins` namespace does not exist. The internal `AgentPlugin`
class name remains only as a compatibility interface for fixed host tool
contributors and is not the Addon protocol or an installable extension API.
