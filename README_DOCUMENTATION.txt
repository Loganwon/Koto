╔═══════════════════════════════════════════════════════════════════════════════╗
║               KOTO CORE SYSTEMS ANALYSIS - COMPLETE DOCUMENTATION              ║
║                          Master Index & Quick Links                            ║
╚═══════════════════════════════════════════════════════════════════════════════╝

📚 DOCUMENTATION SUITE
═════════════════════════════════════════════════════════════════════════════════

This folder contains 4 comprehensive analysis documents of Koto's core systems:

1. 📄 EXECUTIVE_SUMMARY.txt (41 KB) ⭐ START HERE
   ─────────────────────────────────────────────────────────────────────────
   • Complete 5-tier architecture overview
   • Component descriptions with diagrams
   • Key metrics and findings
   • File locations summary
   • Best for: Management, architects, comprehensive understanding

2. 📋 CORE_SYSTEMS_ANALYSIS.txt (12 KB)
   ─────────────────────────────────────────────────────────────────────────
   • Detailed technical analysis of each system
   • Class definitions and method signatures
   • Configuration parameters
   • Integration points
   • Best for: Developers, detailed technical review

3. 📑 QUICK_REFERENCE.txt (13 KB)
   ─────────────────────────────────────────────────────────────────────────
   • Visual ASCII diagrams
   • Quick lookup tables
   • All key patterns and methods
   • File organization
   • Best for: Quick lookups, reference during development

4. 🔍 CLASS_SIGNATURES.txt (22 KB)
   ─────────────────────────────────────────────────────────────────────────
   • Complete class definitions
   • All method signatures with type hints
   • Parameter descriptions
   • 24 plugin class references
   • Best for: API reference, integration work

═════════════════════════════════════════════════════════════════════════════════
                         RECOMMENDED READING ORDER
═════════════════════════════════════════════════════════════════════════════════

For New Team Members:
  1. EXECUTIVE_SUMMARY.txt - Get the big picture
  2. QUICK_REFERENCE.txt - Learn the patterns and organization
  3. CLASS_SIGNATURES.txt - Understand the APIs
  4. CORE_SYSTEMS_ANALYSIS.txt - Deep dive details

For Architects:
  1. EXECUTIVE_SUMMARY.txt (Architecture section)
  2. QUICK_REFERENCE.txt (Diagrams)

For API Users:
  1. QUICK_REFERENCE.txt (Component Locations)
  2. CLASS_SIGNATURES.txt (Method Signatures)
  3. CORE_SYSTEMS_ANALYSIS.txt (Implementation Details)

For Deployers:
  1. EXECUTIVE_SUMMARY.txt (Deployment section)
  2. CORE_SYSTEMS_ANALYSIS.txt (Deployment subsection)

═════════════════════════════════════════════════════════════════════════════════
                           5 CORE SYSTEMS OVERVIEW
═════════════════════════════════════════════════════════════════════════════════

1️⃣  LLM PROVIDER SYSTEM (app/core/llm/)
    ┌─ Abstract Base Class: LLMProvider
    ├─ Implementations: GeminiProvider, OllamaLLMProvider
    └─ Features: Fallback chains, Retry logic, Circuit breaker

2️⃣  AGENT SYSTEM (app/core/agent/)
    ┌─ Abstract Base Classes: Agent, AgentPlugin
    ├─ Implementations: UnifiedAgent, LangGraphAgent, MultiAgentOrchestrator
    ├─ Plugin Registry: 24 plugins for extensibility
    └─ Features: PII filtering, Output validation, Tool routing

3️⃣  ROUTING/DISPATCH SYSTEM (app/core/routing/)
    ┌─ Main Router: SmartDispatcher (hybrid AI + local)
    ├─ Intent Analysis: IntentAnalyzer (multi-turn rewriting)
    ├─ AI Classification: AIRouter (gemini-2.0-flash-lite)
    └─ Task Types: 30+ categories with intelligent routing

4️⃣  SECURITY SYSTEM (app/core/security/)
    ┌─ PII Filtering: 9 detector types with masking
    └─ Output Validation: 8-check quality assurance pipeline

5️⃣  DEPLOYMENT (src/, config/deploy/)
    ┌─ Desktop: PyWebView + Flask (Windows x64)
    ├─ Server: Pure ASGI/WSGI (Linux, cloud)
    ├─ Docker: Multi-stage containerization
    └─ PyInstaller: Standalone executable packaging

═════════════════════════════════════════════════════════════════════════════════
                          KEY METRICS & STATISTICS
═════════════════════════════════════════════════════════════════════════════════

Code Organization:
  • LLM Providers: 2 concrete implementations
  • Agent Types: 3 (UnifiedAgent, LangGraphAgent, MultiAgentOrchestrator)
  • Plugins: 24 total (5 core, 3 optional, 16 full suite)
  • Task Types: 30+ routing categories
  • Deployment Modes: 3 (Desktop, Server, Docker)

Security & Privacy:
  • PII Detectors: 9 types
    - Phone numbers, Landlines, ID cards, Bank cards
    - Email addresses, IPv4, Chinese names, Addresses, Passport/HK/Macau IDs
  • Output Validation: 8 quality checks
  • Masking: <<label-N>> placeholders with restoration maps

Performance:
  • Agent Max Steps: 15 per conversation turn
  • Tool Timeout: 60 seconds per tool execution
  • Validation Retries: Max 1 per response
  • SmartDispatcher Cache: 128 entries LRU
  • AIRouter Cache: 100 entries LRU

Resilience:
  • LLM Retry Policy: 3x with exponential backoff (2s base, 429/503)
  • Circuit Breaker: Backoff on consecutive failures (5s → 120s max)
  • Fallback Chains: Task-specific model hierarchies (10-14 models per task)
  • Interactions API Timeout: 90 seconds (deep-research models)

═════════════════════════════════════════════════════════════════════════════════
                        FILE LOCATION QUICK REFERENCE
═════════════════════════════════════════════════════════════════════════════════

Core Systems:
  app/core/llm/
    ├─ base.py ...................... LLMProvider (ABC)
    ├─ gemini.py .................... GeminiProvider
    ├─ ollama_llm_provider.py ....... OllamaLLMProvider
    ├─ model_fallback.py ............ ModelFallbackExecutor
    └─ langchain_adapter.py ......... LangChain integration

  app/core/agent/
    ├─ base.py ...................... Agent (ABC), AgentPlugin (ABC)
    ├─ unified_agent.py ............ UnifiedAgent (main agent)
    ├─ langgraph_agent.py .......... LangGraphAgent (StateGraph)
    ├─ multi_agent.py .............. MultiAgentOrchestrator
    ├─ tool_registry.py ............ ToolRegistry
    ├─ factory.py ................... Agent factories
    └─ plugins/ ..................... 24 plugin implementations

  app/core/routing/
    ├─ smart_dispatcher.py ......... SmartDispatcher (main router)
    ├─ intent_analyzer.py .......... IntentAnalyzer
    ├─ ai_router.py ................ AIRouter
    ├─ task_classifier.py .......... TaskClassifier
    ├─ task_decomposer.py .......... TaskDecomposer
    └─ local_planner.py ............ LocalPlanner

  app/core/security/
    ├─ pii_filter.py ............... PIIFilter
    └─ output_validator.py ......... OutputValidator

Deployment:
  src/
    ├─ koto_app.py ................. Desktop app (PyWebView + Flask)
    ├─ server.py ................... Web server mode
    ├─ koto_setup.py ............... First-run wizard
    └─ model_downloader.py ......... Model downloader

  config/
    └─ deploy/
        └─ Dockerfile ............. Docker production config

  koto.spec ......................... PyInstaller spec (main exe)
  local_model_installer.spec ........ PyInstaller spec (model downloader)

═════════════════════════════════════════════════════════════════════════════════
                          IMPORTANT PATTERNS & CONVENTIONS
═════════════════════════════════════════════════════════════════════════════════

Design Patterns Used:
  ✓ Abstract Base Classes (ABC) - For interfaces (LLMProvider, Agent, AgentPlugin)
  ✓ Singleton Pattern - ModelFallbackExecutor, PIIFilter (static methods)
  ✓ Factory Pattern - factory.py (create_agent, create_local_agent, etc.)
  ✓ Plugin Architecture - 24 plugins implementing AgentPlugin interface
  ✓ Chain of Responsibility - ModelFallbackExecutor with task-specific chains
  ✓ Circuit Breaker - Cascade failure detection in fallback executor
  ✓ State Machine - LangGraphAgent using LangGraph StateGraph

Configuration Hierarchy:
  1. PIIConfig - PIIFilter configuration
  2. AgentPlugin properties - Plugin metadata
  3. UnifiedAgent parameters - Agent behavior customization
  4. Environment variables - Deployment configuration

Error Handling:
  • Model "not found" errors → trigger fallback
  • Authentication/format errors → propagate immediately (no fallback)
  • Tool execution timeout → return error, don't hang
  • Output validation failure → RETRY or BLOCK action

Async/Concurrent Patterns:
  • ThreadPoolExecutor for tool execution (60s timeout per tool)
  • Background Flask server in desktop app
  • LRU caches with thread-safe locks (SmartDispatcher, PIIFilter)

═════════════════════════════════════════════════════════════════════════════════
                            COMMON USE CASES
═════════════════════════════════════════════════════════════════════════════════

Creating an Agent:
  from app.core.agent.factory import create_agent
  
  agent = create_agent(api_key="your-key")
  result = agent.run("What's the weather today?")

Using PII Filter:
  from app.core.security.pii_filter import PIIFilter, PIIConfig
  
  result = PIIFilter.mask("My phone is 13812345678")
  # result.masked_text = "My phone is <<手机号-1>>"
  # result.mask_map = {"<<手机号-1>>": "13812345678"}

Registering a Custom Plugin:
  from app.core.agent.base import AgentPlugin
  from app.core.agent.tool_registry import ToolRegistry
  
  class MyPlugin(AgentPlugin):
      @property
      def name(self) -> str:
          return "my_plugin"
      
      def get_tools(self) -> List[Dict]:
          return [{
              "name": "my_tool",
              "func": my_tool_function,
              "description": "Does something"
          }]
  
  registry = ToolRegistry()
  registry.register_plugin(MyPlugin())

Validating Output:
  from app.core.security.output_validator import OutputValidator
  
  result = OutputValidator.validate(
      text="Some LLM response",
      skill_id="summarize_doc"
  )
  if result.action == "PASS":
      print(result.text)

Routing User Input:
  from app.core.routing.smart_dispatcher import SmartDispatcher
  
  task_type, confidence, source = SmartDispatcher.analyze("写一个Python函数")
  # Returns: ("CODER", "HIGH", "AI")

═════════════════════════════════════════════════════════════════════════════════
                         TROUBLESHOOTING & DEBUGGING
═════════════════════════════════════════════════════════════════════════════════

Common Issues:

1. "Model not found" errors keep happening
   → Check ModelFallbackExecutor._unavailable dict
   → Mark model as unavailable: executor.mark_unavailable(model_id)
   → Circuit breaker might be active (check _cascade_failures)

2. Tools not executing
   → Check ThreadPoolExecutor timeout (default 60s in tool_registry.py)
   → Verify tool is registered in ToolRegistry
   → Check tool function signature matches schema

3. PII not being masked
   → Enable mask_* flags in PIIConfig
   → Verify pattern matches your data format
   → Check custom_keywords for exact phrase matches

4. Output validation always RETRY/BLOCK
   → Check refusal patterns (model refusing task)
   → Verify skill_id if using format checking
   → Check for internal prompt leaks (PII placeholders in response)

5. Routing to wrong task type
   → Disable AIRouter (USE_AI_ROUTER=False) to use local algorithm
   → Check task corpus matches your input keywords
   → Verify intent rewriting for multi-turn conversations

═════════════════════════════════════════════════════════════════════════════════

Generated: 2026-03-17 23:48:19
Total Documentation: 66+ KB across 4 files
Scope: All 5 core systems + deployment

For updates or corrections, please refer to source files in:
  • app/core/llm/
  • app/core/agent/
  • app/core/routing/
  • app/core/security/
  • src/ (deployment)

