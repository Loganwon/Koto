"""
E2E Test — 真实 Gemini API 端到端测试
验证 UnifiedAgent 完整 ReAct 循环:
  LLM 调用 → 工具选择 → 工具执行 → 观察 → 最终回答
"""

import os
import sys

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

# Load API key the same way web/app.py does
config_path = os.path.join(PROJECT_ROOT, "config", "gemini_config.env")
load_dotenv(config_path)

key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
if not key:
    print("❌ No API key found in config/gemini_config.env")
    sys.exit(1)
print(f"Key loaded: {key[:8]}...{key[-4:]}")

# Proxy
proxy = os.getenv("FORCE_PROXY", "")
if proxy:
    os.environ["HTTP_PROXY"] = proxy
    os.environ["HTTPS_PROXY"] = proxy
    print(f"Proxy set: {proxy}")

# Create agent
from app.core.agent.factory import create_agent

agent = create_agent(model_id="gemini-2.0-flash")
print(f"Agent created, model={agent.model_id}")
print(f"LLM client initialized: {agent.llm.client is not None}")
print(f"Tools registered: {len(agent.registry.get_definitions())}")


def run_test(label, query):
    print()
    print("=" * 60)
    print(f"TEST: {label}")
    print(f"Query: {query}")
    print("=" * 60)
    steps = []
    for step in agent.run(input_text=query):
        d = step.to_dict()
        stype = d["step_type"].upper()
        content = d["content"] or ""
        print(f"  [{stype:12s}] {content[:150]}")
        if d.get("action"):
            a = d["action"]
            print(f"{'':15s} tool={a['tool_name']} args={a['tool_args']}")
        if d.get("observation"):
            print(f"{'':15s} obs={d['observation'][:120]}")
        steps.append(d)

    # Verify we got an ANSWER step
    step_types = [s["step_type"] for s in steps]
    has_answer = "answer" in step_types
    has_action = "action" in step_types
    print(f"\n  Steps: {step_types}")
    print(f"  Has tool call: {has_action}")
    print(f"  Has answer:    {has_answer}")
    if has_answer:
        print(f"  ✅ PASSED")
    else:
        print(f"  ❌ FAILED — no answer step produced")
    return has_answer


# --- Test 1: calculate (tool call expected) ---
t1 = run_test(
    "Calculate with tool", "Please calculate 42 * 17 using the calculate tool."
)

# --- Test 2: get_current_time (tool call expected) ---
t2 = run_test(
    "Current time with tool",
    "What is the current date and time? Use the get_current_time tool.",
)

# --- Test 3: simple chat (no tool call expected) ---
t3 = run_test("Simple chat (no tools)", "Hi Koto, what's your name?")

print()
print("=" * 60)
results = [("calculate", t1), ("current_time", t2), ("simple_chat", t3)]
passed = sum(1 for _, r in results if r)
print(f"Results: {passed}/{len(results)} passed")
for name, ok in results:
    print(f"  {'✅' if ok else '❌'} {name}")
print("=" * 60)
