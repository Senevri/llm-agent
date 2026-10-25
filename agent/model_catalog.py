import os
import sys
import requests
from openai import OpenAI
from mistralai.client import Mistral
from get_ip import get_gateway_ip
from dotenv import load_dotenv

try:
    load_dotenv()
except Exception as e:
    load_dotenv("/agent/.env")

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
        return [m.id for m in models_response.data]
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

def get_all_models():
    return {
        "ollama": list_ollama_models(),
        "mistral": list_mistral_models(),
        "koboldcpp": list_koboldcpp_models()
    }

def main():
    print("Fetching available models...")
    # get argument to specify backend if needed
    # e.g., python model_catalog.py ollama

    backend_map = {
        "ollama": list_ollama_models,
        "mistral": list_mistral_models,
        "koboldcpp": list_koboldcpp_models
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
