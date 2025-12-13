import subprocess
import logging
import socket
import platform
import os  # <--- Added os import

logger = logging.getLogger(__name__)

# LOGIC: Read env var. Default to TRUE if missing.
# We only turn it off if explicitly set to "false" (case-insensitive)
env_mock = os.getenv("MOCK_MODE", "true").lower()
MOCK_MODE = env_mock != "false"

if MOCK_MODE:
    logger.info("SYSTEM: Running in MOCK MODE (Simulated Hardware)")
else:
    logger.info("SYSTEM: Running in LIVE MODE (Real Hardware Access)")

class SystemService:
    def get_hostname(self):
        """Returns the current device hostname"""
        if MOCK_MODE:
            return "MangaServer-Simulated"
        return socket.gethostname()

    def set_hostname(self, new_name):
        """
        Updates the hostname.
        On Pi: Runs hostnamectl
        On Laptop: Just logs it (Safety first!)
        """
        # Validate name (simple alphanumeric check)
        clean_name = "".join(c for c in new_name if c.isalnum() or c == "-")
        
        if MOCK_MODE:
            logger.info(f"[MOCK] Setting hostname to: {clean_name}")
            return True, "Hostname simulation updated (Restart required)"
            
        try:
            # Update hostname via systemd
            # Note: This changes the transient and static hostname
            subprocess.run(["sudo", "hostnamectl", "set-hostname", clean_name], check=True)
            
            # Updating /etc/hosts is tricky from a script, but hostnamectl handles the core identity.
            # A reboot is usually required for mDNS to fully pick up the change.
            return True, "Hostname updated. Please reboot the Pi."
        except Exception as e:
            logger.error(f"Failed to set hostname: {e}")
            return False, str(e)

    def get_wifi_status(self):
        """
        Returns: { 'mode': 'client'|'hotspot', 'ssid': 'MyWifi', 'ip': '192...' }
        """
        if MOCK_MODE:
            return {
                "status": "connected",
                "mode": "client", 
                "ssid": "Home_Network_Sim",
                "ip": "192.168.1.69"
            }
            
        # REAL IMPLEMENTATION
        try:
            # Check general connectivity
            # Output format: STATE
            res = subprocess.run(["nmcli", "-t", "-f", "STATE", "general"], capture_output=True, text=True)
            state = res.stdout.strip()
            
            # Get active connection details
            # We look for the active connection that is NOT 'lo' (loopback) or 'docker0'
            # This is a basic implementation; might need tweaking for specific Pi setups
            res_con = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], capture_output=True, text=True)
            
            active_ssid = "Unknown"
            mode = "client" # default assumption
            
            for line in res_con.stdout.splitlines():
                if "wifi" in line:
                    parts = line.split(":")
                    active_ssid = parts[0]
                    # If the connection name matches our known Hotspot profile name
                    if active_ssid == "MangaHotspot": 
                        mode = "hotspot"
                    break
            
            # Get IP Address (hostname -I is robust)
            res_ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
            ip_addr = res_ip.stdout.split(" ")[0].strip() if res_ip.stdout else "0.0.0.0"

            return {
                "status": state,
                "mode": mode,
                "ssid": active_ssid,
                "ip": ip_addr
            }
        except Exception as e:
            logger.error(f"Failed to read system status: {e}")
            return {"status": "error", "mode": "unknown", "ssid": "Error", "ip": "0.0.0.0"}

    def toggle_hotspot(self, enable_hotspot: bool):
        """
        Switches between Client connection and Hotspot AP.
        Requires pre-configured connections named 'MangaClient' and 'MangaHotspot' in NetworkManager.
        """
        if MOCK_MODE:
            state = "Hotspot" if enable_hotspot else "Client Mode"
            logger.info(f"[MOCK] Switching network mode to: {state}")
            return True, f"Simulated switch to {state}"

        try:
            if enable_hotspot:
                # 1. Bring down client connection (optional, but safer to avoid dual-mode conflicts on some chips)
                subprocess.run(["sudo", "nmcli", "con", "down", "MangaClient"])
                
                # 2. Bring up Hotspot
                subprocess.run(["sudo", "nmcli", "con", "up", "MangaHotspot"], check=True)
                return True, "Switched to Hotspot Mode"
            else:
                # 1. Bring up Client
                subprocess.run(["sudo", "nmcli", "con", "up", "MangaClient"], check=True)
                return True, "Switched to Client Mode"
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Network switch failed: {e}")
            return False, "Failed to switch network. Verify connection profiles exist."

# Singleton instance
manager = SystemService()