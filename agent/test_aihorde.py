from api_endpoint import BACKEND_MAP

_backend = BACKEND_MAP["aihorde"]()
_backend.model = "koboldcpp/.\\LFM3-1.7B-Q8_0.gguf"

client, model = _backend.get_client()
request = client.chat.completions.create(
    model = model,
    messages = [
        {"role": "user", "content": "say hello in five words"}
        ],
    max_tokens=512
)
from pprint import pprint
pprint(request)