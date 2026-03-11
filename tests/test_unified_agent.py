import json
import logging
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.core.agent.plugins.basic_tools_plugin import BasicToolsPlugin
from app.core.agent.types import AgentStepType
from app.core.agent.unified_agent import UnifiedAgent
from app.core.llm.gemini import GeminiProvider

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def test_agent():
    print("Initializing Agent...")

    # Initialize Provider (ensure GOOGLE_API_KEY is in env)
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Warning: GOOGLE_API_KEY not found in environment variables.")
        # Attempt to load from .env or similar if needed, or rely on user having it set

    provider = GeminiProvider(api_key=api_key)

    # Create Agent
    agent = UnifiedAgent(llm_provider=provider, model_id="gemini-1.5-flash")

    # Register Plugin
    plugin = BasicToolsPlugin()
    agent.registry.register_plugin(plugin)

    tools_def = agent.registry.get_definitions()
    print("Agent initialized with tools:", [t["name"] for t in tools_def])
    print("Tool Definitions:", json.dumps(tools_def, indent=2))

    query = "What is 15 * 4? Also tell me what time it is."
    print(f"\nQuery: {query}\n")

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
    test_agent()
