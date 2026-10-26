import subprocess
import datetime

def collect_system_info():
    """Collects and summarizes system information."""
    try:
        os_info = subprocess.check_output(["uname", "-a"], text=True).strip()
        mem_info = subprocess.check_output(["free", "-h"], text=True).strip()
        disk_info = subprocess.check_output(["df", "-h", "/"], text=True).strip()
        uptime_info = subprocess.check_output(["uptime"], text=True).strip()
        
        report = f"--- System Information Report ---\n"
        report += f"Date: {datetime.datetime.now()}\n"
        report += f"OS: {os_info}\n"
        report += "--------------------------------\n"
        report += f"Memory Usage:\n{mem_info}\n"
        report += "--------------------------------\n"
        report += f"Disk Usage:\n{disk_info}\n"
        report += "--------------------------------\n"
        report += f"CPU Load:\n{uptime_info}\n"
        report += "--------------------------------\n"
        return report
    except Exception as e:
        return f"Error collecting system information: {str(e)}"

if __name__ == "__main__":
    print(collect_system_info())
