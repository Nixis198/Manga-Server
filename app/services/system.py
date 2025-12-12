import subprocess
import logging
import socket
import platform

logger = logging.getLogger(__name__)

# Set this to False when running on the actual Raspberry Pi
MOCK_MODE = True 

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
            subprocess.run(["sudo", "hostnamectl", "set-hostname", clean_name], check=True)
            return True, "Hostname updated. Please reboot."
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
                "mode": "client", # or 'hotspot'
                "ssid": "Home_Network_Sim",
                "ip": "192.168.1.69"
            }
            
        # REAL IMPLEMENTATION (For later on Pi)
        # We would parse the output of: nmcli -t -f ACTIVE,SSID,MODE dev wifi
        return {"status": "unknown", "mode": "unknown", "ssid": "", "ip": ""}

    def toggle_hotspot(self, enable_hotspot: bool):
        """
        Switches between Client connection and Hotspot AP.
        """
        if MOCK_MODE:
            state = "Hotspot" if enable_hotspot else "Client Mode"
            logger.info(f"[MOCK] Switching network mode to: {state}")
            return True, f"Simulated switch to {state}"

        # REAL IMPLEMENTATION PLAN (For later):
        # if enable_hotspot:
        #    subprocess.run(["sudo", "nmcli", "con", "up", "MangaHotspot"])
        # else:
        #    subprocess.run(["sudo", "nmcli", "con", "up", "MangaClient"])
        
        return False, "Not implemented on hardware yet"

# Singleton instance
manager = SystemService()