"""Thin adapter over upstream smolagents.ToolCallingAgent, not a reimplementation."""

import json
from copy import deepcopy


class SmolEngine:
    name = "smolagents"

    def __init__(self, config, max_models=60):
        self.config = config
        self.max_models = max_models
        self.agent = None

    def run(self, broker, prompt, message):
        from smolagents import Tool, ToolCallingAgent, OpenAIServerModel

        engine = self

        class BrokerTool(Tool):
            skip_forward_signature_validation = True

            def __init__(self, spec):
                self.name = spec["name"]
                self.description = spec["description"]
                self.inputs = deepcopy(spec["parameters"]["properties"])
                self.output_type = "object"
                for name, value in self.inputs.items():
                    value.setdefault("type", "any")
                    value.setdefault("description", name)
                    if name not in spec["parameters"]["required"]:
                        value["nullable"] = True
                super().__init__()

            def forward(self, **kwargs):
                return broker.invoke(
                    self.name, {k: v for k, v in kwargs.items() if v is not None}
                )

        class TracedModel(OpenAIServerModel):
            requests = 0

            def generate(self, *args, **kwargs):
                self.requests += 1
                broker.turn.model_step = self.requests
                if self.requests > engine.max_models or not broker.permitted():
                    raise RuntimeError("Model request budget exhausted or stopped")
                broker.store.event(
                    broker.task,
                    "model_requested",
                    {"engine": "smolagents", "turn": broker.turn.number},
                )
                result = super().generate(*args, **kwargs)
                usage = getattr(result, "token_usage", None)
                broker.store.event(
                    broker.task,
                    "model_completed",
                    {
                        "engine": "smolagents",
                        "usage": usage.dict() if hasattr(usage, "dict") else str(usage),
                    },
                )
                return result

        tools = [BrokerTool(spec) for spec in broker.definitions()]
        if self.agent is None:
            model = TracedModel(
                model_id=self.config.model,
                api_base=self.config.base_url,
                api_key=self.config.api_key,
                client_kwargs={"timeout": 30, "max_retries": 2},
                temperature=0,
                max_tokens=8192,
            )

            def checkpoint(*_args, **_kwargs):
                if (
                    broker.turn.cancelled.is_set()
                    or broker.turn.writes
                    and broker.store.get(broker.task)["review"]
                ):
                    self.agent.interrupt()

            self.agent = ToolCallingAgent(
                tools=tools,
                model=model,
                instructions=prompt,
                add_base_tools=False,
                max_steps=self.max_models,
                verbosity_level=-1,
                step_callbacks=[checkpoint],
            )
        else:
            self.agent.instructions = prompt
            self.agent.tools = {t.name: t for t in tools} | {
                "final_answer": self.agent.tools["final_answer"]
            }
        self.agent.model.requests = 0
        try:
            answer = self.agent.run(message, reset=False)
        except Exception:
            # Upstream interrupt raises AgentError after the real tool has
            # committed. Only a verified host review checkpoint is a pause.
            if broker.turn.writes and broker.store.get(broker.task)["review"]:
                return "这一处已写入并读回，等你检查。"
            raise
        if broker.turn.writes and broker.store.get(broker.task)["review"]:
            return "这一处已写入并读回，等你检查。"
        return (
            answer
            if isinstance(answer, str)
            else json.dumps(answer, ensure_ascii=False)
        )

    def close(self):
        if self.agent:
            self.agent.model.client.close()
