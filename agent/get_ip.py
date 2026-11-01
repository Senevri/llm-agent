import platform

class GatewayIPError(Exception):
    pass

def get_gateway_ip():
    try:
        # are we in windows?
        if platform.system() == "Windows":
            import subprocess
            # windows: use 'route print' and parse output
            result = subprocess.run(["route", "print"], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if "Default Gateway" in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]  # The gateway IP is usually the third column
                    raise GatewayIPError("Default gateway not found")
        else:
        #linux: read /proc/net/route
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
        raise GatewayIPError(f"Error reading route: {e}")
    return "Gateway not found"

if __name__ == "__main__":
    print(f"Parent/Gateway IP: {get_gateway_ip()}")