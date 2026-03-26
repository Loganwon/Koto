import sys
import logging
logging.basicConfig(level=logging.DEBUG)

from app.core.llm.provider_factory import get_provider

provider = get_provider("gemini", model_id="gemini-3.1-flash")
print("Provider:", provider)
try:
    result = provider.generate_content("hello", model="gemini-3.1-flash", stream=True)
    if hasattr(result, '__iter__'):
        for chunk in result:
            print("Chunk:", chunk)
    else:
        print("Result:", result)
except Exception as e:
    print("Error:", e)

from web.token_tracker import get_stats
print(get_stats())