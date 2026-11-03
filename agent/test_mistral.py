# quickstart.py
import os
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="ministral-14b-2512")

    #"codestral-2508"
    #"ministral-14b-latest"
    args = parser.parse_args()

load_dotenv(Path(__file__).parent / ".env")

client = OpenAI(
    api_key=os.getenv("MISTRAL_API_KEY"),
    base_url=os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
    )

response = client.chat.completions.create(
        #model="ministral-14b-2512",
        #model="zai-glm-5-3-flash",
        model=args.model,
        messages=[
            {"role": "user", "content": "What is Mistral AI?"}
            ],
        )

print(response.choices[0].message.content)
