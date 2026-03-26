import os
os.environ.setdefault('GEMINI_API_KEY', 'AIzaSyDNWGSBRXkSgrhhujQ_VWr5HP0tt_3vTyE')
from google import genai

client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

# Test 1: Non-streaming
print("=== 测试 gemini-3-flash-preview ===")
try:
    r = client.models.generate_content(model='gemini-3-flash-preview', contents='用中文说"可以用"')
    print("非流式调用: OK →", r.text[:80])
except Exception as e:
    print("非流式调用: FAIL →", e)

# Test 2: Streaming
print("\n=== 测试流式输出 ===")
try:
    chunks = []
    for chunk in client.models.generate_content_stream(
        model='gemini-3-flash-preview',
        contents='写一句话描述春天，不超过20字'
    ):
        if chunk.text:
            chunks.append(chunk.text)
            print(f"  chunk: {repr(chunk.text)}")
    print("流式调用: OK → 共", len(chunks), "个chunk，总长", sum(len(c) for c in chunks), "字")
except Exception as e:
    print("流式调用: FAIL →", e)
