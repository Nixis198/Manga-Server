import subprocess
import time
import logging
import os

# CONFIGURATION
CHECK_INTERVAL = 60      # How often to check (seconds)
MAX_FAILURES = 3         # How many fails before switching
HOTSPOT_NAME = "MangaHotspot"
CLIENT_NAME = "MangaClient"
LOG_FILE = "/data/logs/wifi_watchdog.log"

# Ensure log dir exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def check_connection():
    """
    Returns True if we are connected to a network (have an IP).
    Returns False if we are disconnected.
    """
    try:
        # Check if we have an IP address
        # 'hostname -I' returns a space-separated list of IPs. Empty if no connection.
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
        ip_addresses = result.stdout.strip()
        
        if not ip_addresses:
            return False
            
        # Optional: Check if we are already in Hotspot mode (10.42.x.x)
        # If we are already a Hotspot, we count as "Connected" so we don't keep restarting it.
        if "10.42.0.1" in ip_addresses:
            return True
            
        return True
    except Exception as e:
        logging.error(f"Check failed: {e}")
        return False

def switch_to_hotspot():
    """
    Forces the network manager to switch to Hotspot mode.
    """
    logging.warning("FAIL LIMIT REACHED. Switching to Hotspot Mode...")
    try:
        # 1. Bring down client (just in case)
        subprocess.run(["sudo", "nmcli", "con", "down", CLIENT_NAME], check=False)
        time.sleep(2)
        
        # 2. Bring up Hotspot
        subprocess.run(["sudo", "nmcli", "con", "up", HOTSPOT_NAME], check=True)
        
        # 3. Restart Avahi (mDNS)
        time.sleep(3)
        subprocess.run(["sudo", "systemctl", "restart", "avahi-daemon"], check=False)
        
        logging.info("Successfully switched to Hotspot.")
    except Exception as e:
        logging.error(f"Failed to switch: {e}")

def main():
    logging.info("Watchdog started.")
    fail_count = 0
    
    # Wait a bit on startup for system to settle
    time.sleep(30)
    
    while True:
        if check_connection():
            if fail_count > 0:
                logging.info("Connection restored.")
            fail_count = 0
        else:
            fail_count += 1
            logging.warning(f"Connection check failed ({fail_count}/{MAX_FAILURES})")
            
            if fail_count >= MAX_FAILURES:
                switch_to_hotspot()
                # Reset counter so we don't try to switch again immediately
                # We assume we are now in Hotspot mode (which returns True in check_connection)
                fail_count = 0
                
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()