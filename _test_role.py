import os
import dotenv
dotenv.load_dotenv('config/gemini_config.env')

from app.core.llm.gemini import GeminiProvider

llm = GeminiProvider()
llm_model = "gemini-3-flash-preview"

messages = [
    {"role": "user", "content": "What is the weather?"},
    {"role": "assistant", "tool_calls": [{"name": "get_weather", "args": {}}]},
    {"role": "function", "name": "get_weather", "content": '{"weather": "sunny"}'}
]

res = llm.generate_content(prompt=messages, model=llm_model, temperature=0)
print(res.get("text", res.get("content", "")))
