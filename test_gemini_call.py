import json
import os
import sys
sys.path.append(os.getcwd())

from app.api.skill_marketplace_routes import fetch_online_prompts
from app.core.llm.gemini import GeminiProvider
import dotenv
dotenv.load_dotenv("config/gemini_config.env")

prompts = fetch_online_prompts()
print("got prompts:", len(prompts))
query = "翻译助手"

# Build catalog summary: id -> title + desc
catalog_lines = []
for i, p in enumerate(prompts):
    desc = p.get("description", "").replace("\n", " ")[:60]
    catalog_lines.append(f"[{i}] {p['name']} - {desc}")
    
catalog_text = "\n".join(catalog_lines)
print("catalog text length:", len(catalog_text))

rank_prompt = (
    f"Here is a catalog of available skills:\n"
    f"{catalog_text}\n\n"
    f'The user needs: "{query}"\n\n'
    "Pick the best 3 to 10 matching skills. The user's query might be in Chinese, "
    "the titles/descriptions in English — use semantic understanding to match.\n"
    "If none match well, return an empty array.\n"
    "IMPORTANT: Return ONLY a valid JSON array of their integer IDs (e.g. [12, 45, 102]). No markdown, no explanations."
)

llm = GeminiProvider()
try:
    res = llm.generate_content(
        prompt=rank_prompt,
        model="gemini-2.5-flash",
        system_instruction="You are a highly capable semantic matching AI. You return only a JSON array of integers.",
        temperature=0.1,
        max_tokens=256,
    )
    print("Gemini response is:", res)
    content = (res.get("content") or res.get("text") or "") if isinstance(res, dict) else str(res)
    print("content string:", content)
except Exception as e:
    print("Error calling Gemini:", e)
