# cloud_image_gen.py

import requests
import urllib.parse
import os
import sys
import random
from pathlib import Path



if Path(__file__).resolve().parent.parent not in sys.path and Path("/agent") not in sys.path:
    sys.path.append("/agent")

from dotenv import load_dotenv
load_dotenv()



def generate_cloud_image(prompt: str, output_path: str = "/workspace/image.png", width: int = 1024, height: int = 1024, mode="pollinations"):
    valid_modes = ["pollinations", "hf"]
    if mode=="pollinations":
        if os.getenv("POLLINATIONS_API_KEY"):
            return _generate_pollinations_image(prompt, output_path, width, height)
        return "Error: POLLINATIONS_API_KEY not set"
    elif mode=="hf":
        if os.getenv("HF_TOKEN"):
            return _generate_image_hf(prompt, output_path)
        return "Error: HF_TOKEN not set"
    else:
        raise ValueError(f"Invalid mode: {mode}. Valid modes: {valid_modes}")

def _generate_pollinations_image(
        prompt: str,
        output_path: str = "/workspace/image.png",
        width: int = 1024, height: int = 1024,
        model = "black-forest-labs/flux.1-schnell") -> str:
    """
    Generates an image from a text prompt using Pollinations.ai.
    No API key required.
    """
    encoded_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 999999) # Prevent caching if agent iterates on prompts

    url = (f"https://gen.pollinations.ai/image/{encoded_prompt}"
        f"?width={width}&height={height}"
        f"&nologo=true&seed={seed}"
        f"&model={model}")

    try:
        Path(os.path.dirname(output_path)).mkdir(parents=True, exist_ok=True)

        # Pollinations can take 10-30s for high quality images

        # If api key is set, use that
        api_key = os.getenv("POLLINATIONS_API_KEY")
        if api_key:
            headers = {"Authorization": f"Bearer {api_key}"}
            response = requests.get(url, headers=headers, timeout=120, stream=True)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return f"Image successfully generated and saved to: {output_path}"

        response = requests.get(url, timeout=120, stream=True)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return f"Image successfully generated and saved to: {output_path}"
    except Exception as e:
        return f"Error generating image: {e}"


import requests
import time
import os
from pathlib import Path

def _generate_image_hf(prompt: str, output_path: str = "/workspace/image.png", hf_token: str = None) -> str:
    """
    Generates an image using the Qwen Image 2.1 Hugging Face Space API.
    """
    base_url = "https://linoyts-qwen-image-2-1-realtime.hf.space"
    api_base = f"{base_url}/gradio_api"

    headers = {}
    token = hf_token or os.getenv("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 1. Find the correct endpoint name via /info
    try:
        info_resp = requests.get(f"{api_base}/info", headers=headers, timeout=10)
        info_resp.raise_for_status()
        api_info = info_resp.json()

        endpoints = api_info.get("named_endpoints", {})
        endpoint_name = None
        for ep in endpoints.keys():
            if "generate" in ep.lower() or "infer" in ep.lower():
                endpoint_name = ep.lstrip('/')
                break

        if not endpoint_name and endpoints:
            endpoint_name = list(endpoints.keys())[0].lstrip('/')

        if not endpoint_name:
            return "Error: Could not find a generation endpoint in the API info."

    except Exception as e:
        return f"Error fetching API info: {e}"

    # 2. Call the endpoint (POST /call/v2/{endpoint})
    call_url = f"{api_base}/call/v2/{endpoint_name}"
    payload = {"prompt": prompt} # Assuming the param is named "prompt"

    try:
        call_resp = requests.post(call_url, json=payload, headers=headers, timeout=30)
        call_resp.raise_for_status()
        event_data = call_resp.json()
        event_id = event_data.get("event_id")
        if not event_id:
            return f"Error: No event_id returned. Response: {event_data}"
    except Exception as e:
        return f"Error calling generation endpoint: {e}"

    # 3. Poll for result (GET /call/{endpoint}/{event_id})
    poll_url = f"{api_base}/call/{endpoint_name}/{event_id}"
    result_data = None

    # Poll for up to 10 minutes (free HF spaces can be very slow or queued)
    for _ in range(120):
        try:
            poll_resp = requests.get(poll_url, headers=headers, timeout=10)
            if poll_resp.status_code == 200:
                result_data = poll_resp.json()
                break
            # HF spaces often return 500 or 202 while processing/queued
        except Exception:
            pass
        time.sleep(5)

    if not result_data:
        return "Error: Timed out waiting for image generation."

    # 4. Extract image URL and download it
    result_array = result_data.get("data", [])
    image_url = None

    for item in result_array:
        if isinstance(item, dict):
            if "url" in item:
                image_url = item["url"]
                break
            elif "path" in item:
                # Gradio FileData format: need to fetch via /file=
                image_url = f"{base_url}/file={item['path']}"
                break
        elif isinstance(item, str) and (item.startswith("http") or item.startswith("/file=")):
            image_url = item if item.startswith("http") else f"{base_url}{item}"
            break

    if not image_url:
        return f"Error: Could not find image URL in result. Data: {result_array}"

    # Download to output_path
    try:
        Path(os.path.dirname(output_path)).mkdir(parents=True, exist_ok=True)
        img_resp = requests.get(image_url, headers=headers, timeout=60, stream=True)
        img_resp.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in img_resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return f"Image successfully generated and saved to: {output_path}"

    except Exception as e:
        return f"Error downloading generated image: {e}"

CLOUD_IMAGE_GEN_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "generate_cloud_image",
        "description": "Generates an image from a text prompt and saves it to a file path. Use this when the user asks for a picture, diagram, or visual representation.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "A highly detailed, descriptive prompt for the image generator."
                },
                "output_path": {
                    "type": "string",
                    "description": "The absolute file path to save the image to (e.g., /workspace/my_image.png)"
                },
                "mode": {
                    "type": "string",
                    "enum": ["pollinations", "hf"],
                    "description": "The mode to use for image generation. Valid modes: pollinations, hf."
                }
            },
            "required": ["prompt", "output_path"]
        }
    }
}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, required=True)
    parser.add_argument("--output_path", type=str, default="/workspace/image.png")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--mode", type=str, default="pollinations")
    args = parser.parse_args()

    print(generate_cloud_image(args.prompt, args.output_path, args.width, args.height))
