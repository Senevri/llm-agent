import os
import sys
import requests
from openai import OpenAI
from mistralai.client import Mistral
from get_ip import get_gateway_ip
from dotenv import load_dotenv
from pathlib import Path

try:
    load_dotenv()
except Exception as e:
    if Path("/agent/.env").exists():
        load_dotenv("/agent/.env")
    else:
        load_dotenv(Path(__file__).parent / ".env")

def list_ollama_models():
    gateway_ip = get_gateway_ip()
    url = f"http://{gateway_ip}:11434/api/tags"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return [m['name'] for m in data.get('models', [])]
    except Exception as e:
        return [f"Error: {e}"]

def list_mistral_models(api_key=None):
    if not api_key:
        # Try to load from /agent/.env if not provided
        api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        return ["Error: No Mistral API key provided or found in /agent/.env"]
    try:
        client = Mistral(api_key=api_key)
        models_response = client.models.list()
        return [m.id for m in models_response.data] # type: ignore
    except Exception as e:
        return [f"Error: {e}"]

def list_koboldcpp_models():
    gateway_ip = get_gateway_ip()
    # Typical KoboldCPP port is 5001
    url = f"http://{gateway_ip}:5001/api/v1/models"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        # KoboldCPP API might vary; check for 'data' or 'models'
        if 'data' in data:
            return [m['id'] for m in data['data']]
        return [str(data)]
    except Exception as e:
        return [f"Error: {e} (Backend likely not running)"]

def get_openai_models(base_url, api_key):

    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root = f"{root}/v1"

    # Resolve API key from arguments or environment
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")

    headers = {}
    if resolved_api_key:
        headers["Authorization"] = f"Bearer {resolved_api_key}"
    try:
        # Query the standard OpenAI-compatible model list endpoint
        r = requests.get(f"{root}/models", headers=headers, timeout=5)
        r.raise_for_status()

        return r.json().get("data", [])
    except Exception:
        # Silently fail and fall back to default (network error, bad key, or endpoint doesn't support it)
        pass

def list_openai_models():
    models = get_openai_models(
        f"{os.getenv('OPENAI_BASE_URL', 'http://localhost:8080')}/v1",
        os.getenv("OPENAI_API_KEY")
        )
    if models:
        return [m['id'] for m in models]

def list_llamacpp_models():
    gateway_ip = get_gateway_ip()
    url = f"http://{gateway_ip}"
    try:
        response = get_llamacpp_models(url, port=os.getenv("LLAMA_PORT", "9931"))
        data = response.json()
        return [m['id'] for m in data.get('data', [])]
    except Exception as e:
        return [f"Error: {e}"]

def get_llamacpp_models(base_url, port="9931"):
    # /api/v1/model
    if not base_url:
        gateway_ip = get_gateway_ip()
        base_url = f"http://{gateway_ip}:{port}"
    available_models = requests.get(base_url + "/models")
    # format: {"result": "<model_name
    return available_models.json().get("models", [])


def get_all_models():
    return {
        "ollama": list_ollama_models(),
        "mistral": list_mistral_models(),
        "koboldcpp": list_koboldcpp_models(),
        "openai": list_openai_models()
    }

MODEL_CATALOGS = {
    "ollama": list_ollama_models,
    "mistral": list_mistral_models,
    "koboldcpp": list_koboldcpp_models,
    "llamacpp": list_llamacpp_models,
    "openai": list_openai_models
}

def main():
    print("Fetching available models...")
    # get argument to specify backend if needed
    # e.g., python model_catalog.py ollama

    backend_map = {
        "ollama": list_ollama_models,
        "mistral": list_mistral_models,
        "koboldcpp": list_koboldcpp_models,
        "llamacpp": list_llamacpp_models,
        "openai": list_openai_models
    }

    if len(sys.argv) > 1:
        cmd  = sys.argv[1].lower()
        if cmd == "--backend" and len(sys.argv) > 2:
            backend = sys.argv[2].lower()
        else:
            # print info
            print("Usage: python model_catalog.py --backend <backend_name>")
            print("Available backends: ollama, mistral, koboldcpp")
            return
        if backend in backend_map:
            models = backend_map[backend]()
            print(f"\n--- {backend.upper()} ---")
            if models:
                for m in models:
                    print(f"- {m}")
            else:
                print("No models found.")
        else:
            print(f"Unknown backend '{backend}'. Available backends: {', '.join(backend_map.keys())}")
        return 0


    results = get_all_models()
    for backend, models in results.items():
        print(f"\n--- {backend.upper()} ---")
        if models:
            for m in models:
                print(f"- {m}")
        else:
            print("No models found.")

if __name__ == "__main__":
    main()
