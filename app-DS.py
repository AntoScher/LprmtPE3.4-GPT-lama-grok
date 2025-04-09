from openai import OpenAI
import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
messages = [{"role": "system", "content": "You are a helpful assistant."}]

while True:
    user_input = input("\nUser: ")
    if user_input.lower() == "exit":
        break

    messages.append({"role": "user", "content": user_input})

    stream = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=True
    )

    print("Assistant: ", end="", flush=True)
    full_response = []
    for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        print(content, end="", flush=True)
        full_response.append(content)

    messages.append({"role": "assistant", "content": "".join(full_response)})