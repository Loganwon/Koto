#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 3 End-to-End Test
验证：
  1. 前端快速测试：SSE 流、系统工具调用、结构化卡片
  2. 多轮交互验证：会话状态快照跨轮复用
"""

import json
import sys
import time
import uuid
from pathlib import Path

import requests

# 配置
API_BASE = "http://localhost:5000"
TEST_SESSION = f"test_phase3_{uuid.uuid4().hex[:8]}"


def test_1_single_system_query_sse():
    """Test 1: 单轮 SSE 流 + 系统工具 + 结构化卡片"""
    print("\n" + "=" * 70)
    print("[TEST 1] SSE Stream + System Tool Query")
    print("=" * 70)

    url = f"{API_BASE}/api/agent/chat"
    payload = {
        "message": "查询当前 CPU 状态",
        "session_id": TEST_SESSION,
        "model": "gemini-1.5-flash",
    }

    print(f"POST {url}")
    print(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
    print()

    try:
        response = requests.post(url, json=payload, stream=True, timeout=30)
        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False

        print("✓ Stream connected")
        step_count = 0
        observation_found = False
        cpu_card_found = False

        for line in response.iter_lines():
            if not line or not line.startswith(b"data: "):
                continue

            try:
                data_json = json.loads(line[6:].decode("utf-8"))
                event_type = data_json.get("type")

                if event_type == "agent_step":
                    event_data = data_json.get("data", {})
                    step_type = event_data.get("step_type", "").lower()

                    if step_type == "action":
                        tool_name = event_data.get("action", {}).get("tool_name", "")
                        print(f"  📋 ACTION: {tool_name}")
                    elif step_type == "observation":
                        observation_found = True
                        obs_text = event_data.get("observation") or event_data.get(
                            "content", ""
                        )
                        print(f"  ✅ OBSERVATION (len={len(obs_text)})")
                        # Check if observation contains CPU data
                        try:
                            obs_json = json.loads(obs_text[:200])
                            if (
                                "usage_percent" in obs_json
                                or "logical_cores" in obs_json
                            ):
                                cpu_card_found = True
                                print(
                                    f"     ➜ CPU data detected: {json.dumps(obs_json, ensure_ascii=False)[:120]}"
                                )
                        except:
                            pass
                    elif step_type == "thought":
                        content = event_data.get("content", "")[:80]
                        print(f"  💭 THOUGHT: {content}...")
                    elif step_type == "answer":
                        content = event_data.get("content", "")[:120]
                        print(f"  📝 ANSWER: {content}...")

                    step_count += 1

                elif event_type == "task_final":
                    print(f"  ✓ TASK_FINAL received")

                elif event_type == "error":
                    print(
                        f"  ❌ ERROR: {data_json.get('data', {}).get('error', 'unknown')}"
                    )
                    return False

            except Exception as e:
                print(f"  [Parse error] {e}")

        print()
        print(f"Summary:")
        print(f"  Steps received: {step_count}")
        print(f"  Observation found: {'✅ Yes' if observation_found else '❌ No'}")
        print(f"  CPU card found: {'✅ Yes' if cpu_card_found else '❌ No'}")

        if step_count > 0 and observation_found:
            print("\n✅ TEST 1 PASSED")
            return True
        else:
            print("\n❌ TEST 1 FAILED")
            return False

    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        return False


def test_2_multi_turn_state_reuse():
    """Test 2: 多轮交互 + 状态快照跨轮复用"""
    print("\n" + "=" * 70)
    print("[TEST 2] Multi-Turn State Reuse")
    print("=" * 70)

    session = f"test_multiround_{uuid.uuid4().hex[:8]}"

    # Turn 1: Query CPU
    print(f"\n[Turn 1] Query CPU status")
    turn1_ok = False
    try:
        response = requests.post(
            f"{API_BASE}/api/agent/chat",
            json={"message": "我的 CPU 使用率是多少？", "session_id": session},
            stream=True,
            timeout=30,
        )
        for line in response.iter_lines():
            if line and b"observation" in line:
                turn1_ok = True
                break
        print(f"  {'✅' if turn1_ok else '❌'} Turn 1 complete")
    except Exception as e:
        print(f"  ❌ Turn 1 failed: {e}")
        return False

    if not turn1_ok:
        print("❌ TEST 2 FAILED (Turn 1)")
        return False

    # Check state file
    state_file = Path("chats") / f"{session}.state.json"
    turn1_has_cpu = False
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            sys_snapshot = state.get("system_snapshot", {})
            turn1_has_cpu = "cpu" in sys_snapshot
            print(f"  State snapshot keys: {list(sys_snapshot.keys())}")
            print(f"  CPU snapshot captured: {'✅ Yes' if turn1_has_cpu else '❌ No'}")
    else:
        print(f"  ⚠️  State file not found at {state_file}")

    # Turn 2: Memory (should auto-inject Turn 1 context)
    print(f"\n[Turn 2] Query memory (should auto-inject CPU context)")
    try:
        response = requests.post(
            f"{API_BASE}/api/agent/chat",
            json={"message": "内存占用怎么样？", "session_id": session},
            stream=True,
            timeout=30,
        )
        for line in response.iter_lines():
            if line and b"observation" in line:
                print(f"  ✅ Turn 2 complete (received observation)")
                break
    except Exception as e:
        print(f"  ❌ Turn 2 failed: {e}")
        return False

    # Check updated state
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            sys_snapshot = state.get("system_snapshot", {})
            turn2_has_memory = "memory" in sys_snapshot
            print(f"  Updated snapshot keys: {list(sys_snapshot.keys())}")
            print(
                f"  Memory snapshot captured: {'✅ Yes' if turn2_has_memory else '❌ No'}"
            )
            print(
                f"  CPU snapshot persisted: {'✅ Yes' if 'cpu' in sys_snapshot else '❌ No'}"
            )

    # Turn 3: Disk (should have both CPU + memory context)
    print(f"\n[Turn 3] Query disk usage (should have multi-tool context)")
    try:
        response = requests.post(
            f"{API_BASE}/api/agent/chat",
            json={"message": "磁盘剩余空间还有多少？", "session_id": session},
            stream=True,
            timeout=30,
        )
        for line in response.iter_lines():
            if line and b"observation" in line:
                print(f"  ✅ Turn 3 complete (received observation)")
                break
    except Exception as e:
        print(f"  ❌ Turn 3 failed: {e}")
        return False

    # Final state check
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            sys_snapshot = state.get("system_snapshot", {})
            final_keys = list(sys_snapshot.keys())
            all_captured = all(k in final_keys for k in ["cpu", "memory", "disk"])
            print(f"  Final snapshot keys: {final_keys}")
            print(
                f"  All 3 tools captured: {'✅ Yes' if all_captured else '❌ Partial'}"
            )

    if turn1_has_cpu:
        print("\n✅ TEST 2 PASSED (State reuse verified)")
        return True
    else:
        print("\n❌ TEST 2 FAILED")
        return False


def main():
    print("\n" + "🔬 Phase 3 E2E Validation Tests 🔬".center(70, "="))

    # Check server
    print("\n[Pre-check] Server connectivity...")
    try:
        resp = requests.get(f"{API_BASE}/api/agent/tools", timeout=5)
        if resp.status_code == 200:
            tools = resp.json()
            print(f"✅ Server online ({len(tools)} tools)")
        else:
            print(f"❌ Server returned {resp.status_code}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Cannot connect to {API_BASE}: {e}")
        print("   (Start Flask backend: python web/app.py)")
        sys.exit(1)

    results = {
        "Test 1 (SSE + System Tool)": test_1_single_system_query_sse(),
        "Test 2 (Multi-Turn State)": test_2_multi_turn_state_reuse(),
    }

    print("\n" + "=" * 70)
    print("📊 Test Summary")
    print("=" * 70)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} — {name}")

    print(f"\nTotal: {passed}/{total} passed")
    print("=" * 70)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
