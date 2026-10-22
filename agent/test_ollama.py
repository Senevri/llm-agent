
from openai import OpenAI

def get_gateway_ip():
    try:
        with open("/proc/net/route") as fh:
            for line in fh:
                fields = line.strip().split()
                # Default route has destination 00000000
                if fields[1] == '00000000':
                    gateway_hex = fields[2]
                    # Convert hex string (little-endian) to dotted-decimal IP
                    gateway_ip = '.'.join([str(int(gateway_hex[i:i+2], 16)) for i in (6, 4, 2, 0)])
                    return gateway_ip
    except Exception as e:
        return f"Error reading route: {e}"
    return "Gateway not found"

if __name__ == "__main__":
    print(f"Parent/Gateway IP: {get_gateway_ip()}")

    gateway_ip = get_gateway_ip()


    # Point straight to your local Ollama backend—zero API keys, zero rate limits
    client = OpenAI(
        base_url=f"http://{gateway_ip}:11434/v1",
        api_key="ollama" # Ollama doesn't require a real key, but the client expects a string
    )

    response = client.chat.completions.create(
        model="gemma4:31b-cloud",
        messages=[{"role": "user", "content": "Hello! I am testing calling you from a Python script. Can you respond with a short greeting?"}],
    )

    print(response.choices[0].message.content)