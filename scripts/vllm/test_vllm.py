from openai import OpenAI

# Set OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "EMPTY"
openai_api_base = "http://localhost:8080/v1"

client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

chat_response = client.chat.completions.create(
    model="llama",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. "
                "If you output a reasoning process, you must wrap it with <think> and </think>, "
                "and keep the final answer outside the tags."
            ),
        },
        {"role": "user", "content": "Tell me a joke."},
    ],
)
print("Chat response:", chat_response)
