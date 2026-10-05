import argparse
import sys
from openai import OpenAI

# 1. Point the client to your vLLM server endpoint
# Replace with your HAProxy IP/hostname or local port-forward address (e.g., http://localhost:8000/v1)
DEFAULT_VLLM_BASE_URL = "http://localhost:36651/v1"
DEFAULT_MODEL_NAME = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"  # Match your loaded vLLM model name


def parse_args():
    parser = argparse.ArgumentParser(description="Interactive vLLM prompt client.")
    parser.add_argument(
        "--name",
        dest="model_name",
        default=DEFAULT_MODEL_NAME,
        help=f"Model name to send to the server (default: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument(
        "--host",
        dest="vllm_base_url",
        default=DEFAULT_VLLM_BASE_URL,
        help=f"Base URL for the vLLM OpenAI-compatible API (default: {DEFAULT_VLLM_BASE_URL})",
    )
    return parser.parse_args()


args = parse_args()
client = OpenAI(
    base_url=args.vllm_base_url,
    api_key="EMPTY",  # vLLM doesn't require an API key by default
)


def stream_prompt(prompt: str, model_name: str):
    """Sends a prompt to vLLM using text completion instead of chat completion."""
    try:
        # Use completions.create instead of chat.completions.create
        response = client.completions.create(
            model=model_name,
            prompt=f"User: {prompt}\nAssistant:",
            temperature=0.7,
            stream=True,
            max_tokens=512,
            stop=["User:", "<|endoftext|>"]
        )

        print("\nResponse: ", end="", flush=True)
        for chunk in response:
            content = chunk.choices[0].text
            if content:
                print(content, end="", flush=True)
        print("\n")

    except Exception as e:
        print(f"\n[Error] Failed to connect or generate: {e}\n")


def main():
    print(f"Connected to vLLM at {args.vllm_base_url}")
    print(f"Using model: {args.model_name}")
    print("Type your prompt below. Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            user_input = input("Prompt > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Exiting...")
                break

            stream_prompt(user_input, args.model_name)

        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)


if __name__ == "__main__":
    main()
