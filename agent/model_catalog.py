import os
import sys
import requests
from openai import OpenAI
from mistralai.client import Mistral
from get_ip import get_gateway_ip
from dotenv import load_dotenv
from pathlib import Path
import json

try:
    load_dotenv()
except Exception as e:
    if Path("/agent/.env").exists():
        load_dotenv("/agent/.env")
    else:
        load_dotenv(Path(__file__).parent / ".env")

# Contract:
#   get_<backend>_models() -> {"models": [<raw dicts>]} | {"error": "<msg str>"}
#   list_<backend>_models() -> [<name/id strings>]      | ["Error: <msg>"]

def _model_name(m):
    if isinstance(m, dict):
        return m.get("id") or m.get("name") or m.get("model") or str(m)
    return str(m)

def _list_backend(fetch):
    data = fetch()
    if "error" in data:
        return [f"Error: {data['error']}"]
    return [_model_name(m) for m in data.get("models", [])]


def get_ollama_models() -> dict:
    url = f"http://{get_gateway_ip()}:11434/api/tags"
    try:
        r = requests.get(url, timeout=5); r.raise_for_status()
        return {"models": r.json().get("models", [])}
    except Exception as e:
        return {"error": str(e)}


def list_ollama_models():
    return _list_backend(get_ollama_models)


def get_mistral_models(api_key=None) -> dict:
    api_key = os.getenv("MISTRAL_API_KEY", api_key)
    if not api_key:
        return {"error": "No MISTRAL_API_KEY"}
    try:
        client = Mistral(api_key=api_key)
        return {"models": [m.model_dump() for m in client.models.list().data]}
    except Exception as e:
        return {"error": str(e)}


def list_mistral_models(api_key=None):
    return _list_backend(lambda: get_mistral_models(api_key))


def get_koboldcpp_models() -> dict:
    url = f"http://{get_gateway_ip()}:5001/api/v1/models"
    try:
        r = requests.get(url, timeout=5); r.raise_for_status()
        data = r.json()
        return {"models": data.get("data", data.get("models", []))}
    except Exception as e:
        return {"error": str(e)}


def list_koboldcpp_models():
    return _list_backend(get_koboldcpp_models)


def get_openai_models(base_url=None, api_key=None) -> dict:
    base_url = os.getenv("OPENAI_BASE_URL", base_url or "http://localhost:8080")
    api_key  = os.getenv("OPENAI_API_KEY",  api_key)
    root = str(base_url).rstrip("/")
    if not root.endswith("/v1"):
        root = f"{root}/v1"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        r = requests.get(f"{root}/models", headers=headers, timeout=5)
        r.raise_for_status()
        return {"models": r.json().get("data", [])}
    except Exception as e:
        return {"error": str(e)}


def list_openai_models():
    return _list_backend(get_openai_models)


def get_llamacpp_models(base_url=None, port=None) -> dict:
    port = port or os.getenv("LLAMACPP_PORT", "9931")
    base_url = base_url or f"http://{get_gateway_ip()}:{port}"
    try:
        r = requests.get(f"{base_url}/models", timeout=5); r.raise_for_status()
        data = r.json()
        # llama.cpp server: {"data": [...]} on /v1/models, {"result": "name"} elsewhere
        if "data" in data:
            return {"models": data["data"]}
        if "result" in data:
            return {"models": [{"id": data["result"]}]}
        return {"models": []}
    except Exception as e:
        return {"error": str(e)}


def list_llamacpp_models():
    return _list_backend(get_llamacpp_models)

def get_aihorde_workers() -> list:
    """Native AI Horde worker list (NOT the OAI-compat model catalog)."""
    try:
        r = requests.get("https://aihorde.net/api/v2/workers", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return [{"error": str(e)}]


def list_aihorde_workers():
    """Chat-capable worker model IDs, deduped. Distinct from list_aihorde_models()."""
    data = get_aihorde_workers()
    if isinstance(data, list) and data and isinstance(data[0], dict) and "error" in data[0]:
        return [f"Error: {data[0]['error']}"]
    seen = set()
    out = []
    for w in data:
        if w.get("maintenance_mode"):
            continue
        if not w.get("accepts_chat_jobs", False):
            continue
        mid = (w.get("chat") or {}).get("model_id")
        if mid and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out

def get_aihorde_models() -> dict:
    try:
        r = requests.get("https://oai.aihorde.net/v1/models", timeout=10)
        r.raise_for_status()
        return {"models": r.json().get("data", [])}
    except Exception as e:
        return {"error": str(e)}


def list_aihorde_models():
    return _list_backend(get_aihorde_models)


def get_openrouter_models(api_key=None) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", api_key)
    if not api_key:
        return {"error": "No OPENROUTER_API_KEY"}
    try:
        r = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        r.raise_for_status()
        return {"models": r.json().get("data", [])}
    except Exception as e:
        return {"error": str(e)}


def list_openrouter_models():
    return _list_backend(get_openrouter_models)

def get_all_models():
    return {name: fn() for name, fn in MODEL_CATALOGS.items()}

MODEL_CATALOGS = {
    "ollama": list_ollama_models,
    "mistral": list_mistral_models,
    "koboldcpp": list_koboldcpp_models,
    "llamacpp": list_llamacpp_models,
    "openai": list_openai_models,
    "aihorde": list_aihorde_models,
    "openrouter": list_openrouter_models
}

RAW_FETCHERS = {
    "ollama":     get_ollama_models,
    "mistral":    get_mistral_models,
    "koboldcpp":  get_koboldcpp_models,
    "llamacpp":   get_llamacpp_models,
    "openai":     get_openai_models,
    "aihorde":    get_aihorde_models,
    "openrouter": get_openrouter_models,
}


def main():
    print("Fetching available models...")
    # get argument to specify backend if needed
    # e.g., python model_catalog.py ollama

    backend_map = MODEL_CATALOGS

    backend_raw_map = RAW_FETCHERS

    print(f"Available backends: {",".join(backend_map.keys())}")
    import argparse
    parser = argparse.ArgumentParser(prog="model_catalog.py")
    parser.add_argument("--backend", help="Usage: python model_catalog.py --backend <backend_name>")
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args()

    backend = args.backend

    if backend:
        if  backend in backend_map:
            models = backend_map[backend]()
            print(f"\n--- {backend.upper()} ---")
            if models:
                for m in models:
                    print(f"- {m if isinstance(m, str) else next(iter(m))}")
            else:
                print("No models found.")
        else:
            print(f"Unknown backend '{backend}'. Available backends: {', '.join(backend_map.keys())}")
        return 0

    if not args.raw:
        results = get_all_models()
    else:
        results = {}
        for k, v in backend_raw_map.items():
             if callable(v):
                try:
                    data = v()
                    if isinstance(data, dict):
                        data = data.get("models",
                                        data.get("data",
                                                data))
                    type_ok = any([isinstance(data, _type) for _type in [dict, list, str]])
                    if not type_ok:
                        print(f"{k}: {type(data)}")
                    results[k] = data
                    assert len(results[k]) > 0
                    print(f"{k} okay")
                except Exception as e:
                    print(str(e)[:80])
                    print(f"no models found for {k}")
                    if k in "mistral":
                        exit(1)
                    continue

    assert "mistral" in results
    assert "aihorde" in results
    for backend, models in results.items():
        print(f"\n--- {backend.upper()} ---")
        if models:
            for m in models:
                if not isinstance(m, dict):
                    m = str(m)
                if args.raw:
                    _str = f"- {m}" if isinstance(m, str) else "\n\t".join(f" - {k}: {str(v)}" for k, v in m.items())
                else:
                    _str =f"- {m}" if isinstance(m, str) else "\n\t".join([f" - {k}" for k in m.keys()])
                print(_str[:160])
        else:
            print("No models found.")

if __name__ == "__main__":
    main()
