import subprocess
import logging
import socket
import os
import time

logger = logging.getLogger(__name__)

# Determine Mode
env_mock = os.getenv("MOCK_MODE", "true").lower()
MOCK_MODE = env_mock != "false"

if MOCK_MODE:
    logger.info("SYSTEM: Running in MOCK MODE")
else:
    logger.info("SYSTEM: Running in LIVE MODE")

class SystemService:
    def get_hostname(self):
        if MOCK_MODE: return "MangaServer-Sim"
        return socket.gethostname()

    def set_hostname(self, new_name):
        clean_name = "".join(c for c in new_name if c.isalnum() or c == "-")
        if MOCK_MODE: return True, "Simulated hostname change."
        
        try:
            subprocess.run(["sudo", "hostnamectl", "set-hostname", clean_name], check=True)
            # Try to restart Avahi to broadcast new name immediately
            subprocess.run(["sudo", "systemctl", "restart", "avahi-daemon"], check=False)
            return True, "Hostname updated. Please reboot."
        except Exception as e:
            return False, str(e)

    def get_wifi_status(self):
        if MOCK_MODE:
            return {"status": "connected", "mode": "client", "ssid": "SimWifi", "ip": "192.168.1.50"}
            
        try:
            # 1. Get General Status
            res = subprocess.run(["nmcli", "-t", "-f", "STATE", "general"], capture_output=True, text=True)
            state = res.stdout.strip()
            
            # 2. Get IP Address
            res_ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
            ip_addr = res_ip.stdout.split(" ")[0].strip() if res_ip.stdout else "0.0.0.0"
            
            # 3. Determine Mode
            mode = "client"
            active_ssid = "Unknown"
            
            # CHECK A: Is IP the Hotspot Default?
            if ip_addr.startswith("10.42.0."):
                mode = "hotspot"
                active_ssid = "MangaServer (Hotspot)"
            else:
                # CHECK B: Ask NetworkManager for active connection name
                res_con = subprocess.run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"], capture_output=True, text=True)
                active_con = res_con.stdout.strip()
                
                if "MangaHotspot" in active_con:
                    mode = "hotspot"
                    active_ssid = "MangaServer (Hotspot)"
                elif active_con:
                    # It's a client connection, try to get the actual SSID
                    res_ssid = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], capture_output=True, text=True)
                    for line in res_ssid.stdout.splitlines():
                        if line.startswith("yes:"):
                            active_ssid = line.split(":")[1]
                            break
                    if active_ssid == "Unknown": active_ssid = active_con

            return {
                "status": state,
                "mode": mode,
                "ssid": active_ssid,
                "ip": ip_addr
            }
        except Exception as e:
            logger.error(f"Sys check failed: {e}")
            return {"status": "error", "mode": "unknown", "ssid": "Error", "ip": "0.0.0.0"}

    def toggle_hotspot(self, enable_hotspot: bool):
        if MOCK_MODE: return True, "Simulated Switch"

        try:
            if enable_hotspot:
                # SWITCHING TO HOTSPOT
                logger.info("Switching to HOTSPOT mode...")
                # 1. Force down the client (ignore errors if already down)
                subprocess.run(["sudo", "nmcli", "con", "down", "MangaClient"], check=False)
                time.sleep(2) 
                # 2. Bring up Hotspot
                subprocess.run(["sudo", "nmcli", "con", "up", "MangaHotspot"], check=True)
                
            else:
                # SWITCHING TO CLIENT
                logger.info("Switching to CLIENT mode...")
                # 1. Force down the hotspot
                subprocess.run(["sudo", "nmcli", "con", "down", "MangaHotspot"], check=False)
                time.sleep(2)
                # 2. Bring up Client
                subprocess.run(["sudo", "nmcli", "con", "up", "MangaClient"], check=True)

            # CRITICAL FIX: Restart mDNS (Avahi) so .local works on the new network
            time.sleep(3)
            subprocess.run(["sudo", "systemctl", "restart", "avahi-daemon"], check=False)
            
            return True, "Network switched successfully."
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Network switch failed: {e}")
            return False, f"Switch failed: {e}"

manager = SystemService()