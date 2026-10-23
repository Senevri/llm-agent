# quickstart.py
import os
from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

response = client.chat.complete(
        #model="ministral-14b-2512",
        #model="zai-glm-5-3-flash",
        model="mistral-small-latest",
        messages=[
            {"role": "user", "content": "What is Mistral AI?"}
            ],
        )

print(response.choices[0].message.content)
