import json
import logging
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.core.agent.plugins.file_editor_plugin import FileEditorPlugin
from app.core.agent.types import AgentStepType
from app.core.agent.unified_agent import UnifiedAgent
from app.core.llm.gemini import GeminiProvider

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def test_file_agent():
    print("Initializing File Agent...")

    # Initialize Provider
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Warning: GOOGLE_API_KEY not found. Agent will fail at generation step.")

    provider = GeminiProvider(api_key=api_key)

    # Create Agent
    agent = UnifiedAgent(llm_provider=provider, model_id="gemini-1.5-flash")

    # Register Plugin
    file_plugin = FileEditorPlugin()
    agent.registry.register_plugin(file_plugin)

    tools_def = agent.registry.get_definitions()
    print("Agent initialized with tools:", [t["name"] for t in tools_def])
    print("Tool Definitions:", json.dumps(tools_def, indent=2))

    # Check if schema is correct (UPPERCASE types)
    for tool in tools_def:
        props = tool["parameters"].get("properties", {})
        for prop_name, prop_def in props.items():
            if prop_def["type"] not in [
                "STRING",
                "INTEGER",
                "NUMBER",
                "BOOLEAN",
                "ARRAY",
                "OBJECT",
            ]:
                print(
                    f"WARNING: Tool '{tool['name']}' param '{prop_name}' has invalid type '{prop_def['type']}'"
                )

    query = "Create a file named 'hello_agent.txt' with content 'Hello from Koto Agent!' and then read it back."
    print(f"\nQuery: {query}\n")

    if not api_key:
        return

    print("--- Start Agent Loop ---")
    try:
        steps = agent.run(input_text=query)
        for step in steps:
            if step.step_type == AgentStepType.THOUGHT:
                print(f"[Thought] {step.content}")
            elif step.step_type == AgentStepType.ACTION:
                print(f"[Action] {step.content}")
                print(f"  -> Args: {step.action.tool_args}")
            elif step.step_type == AgentStepType.OBSERVATION:
                print(f"[Observation] {step.content}")
            elif step.step_type == AgentStepType.ANSWER:
                print(f"\n[Answer] {step.content}")
            elif step.step_type == AgentStepType.ERROR:
                print(f"[Error] {step.content}")
    except Exception as e:
        print(f"Execution failed: {e}")


if __name__ == "__main__":
    test_file_agent()
