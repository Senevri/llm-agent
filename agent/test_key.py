import os
import sys
from dotenv import load_dotenv
from openai import OpenAI
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 1. Load variables from .env into environment
load_dotenv()

# 2. Retrieve key
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: GEMINI_API_KEY not found in .env file.")
    sys.exit(1)

print(f"🔑 Key detected (starts with: {api_key[:6]}...)")

try:
    # 3. Initialize client pointing to Google AI Studio's OpenAI endpoint
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )

    # 4. Send a minimal request
    print("⏳ Sending test request to Gemini...")

    response = client.chat.completions.create(
        model="gemini-3.8-flash",
        messages=[
            {"role": "user", "content": "Respond with the word 'Connected!' if you can read this."}
        ],
        max_tokens=10
    )

    # 5. Output response
    logger.debug(response)
    logger.debug(response.choices[0].message)
    result_text = response.choices[0].message.content.strip()
    print(f"\n✅ SUCCESS! Response from model: \"{result_text}\"")

except Exception as e:
    print(f"\n❌ API Test Failed: {str(e)}")