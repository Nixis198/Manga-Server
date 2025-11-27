import os
import shutil
import subprocess
import sys

# Configuration Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
INPUT_DIR = os.path.join(DATA_DIR, "input")
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")
DB_FILE = os.path.join(DATA_DIR, "manga.db")

def run_docker_command(args):
    """Helper to run docker commands in the project directory"""
    try:
        # We set cwd=BASE_DIR so it finds the docker-compose.yml file
        subprocess.run(args, check=True, cwd=BASE_DIR)
    except FileNotFoundError:
        print("Error: 'docker-compose' command not found. Is Docker installed?")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print("Error: Docker command failed.")
        sys.exit(1)

def reset_system():
    print("WARNING: This will STOP the server, reset the database, moves files back to Input, and RESTART the server.")
    confirmation = input("Type 'yes' to proceed: ")
    if confirmation.lower() != 'yes':
        print("Aborted.")
        return

    # --- Step 0: Stop Docker ---
    print("\n[Step 1/5] Stopping Docker Containers...")
    run_docker_command(["docker-compose", "down"])

    # --- Step 1: Move files back ---
    print("\n[Step 2/5] Moving comics back to Input...")
    count = 0
    # Walk through the library to find any ZIP/CBZ files
    for root, dirs, files in os.walk(LIBRARY_DIR):
        for file in files:
            if file.lower().endswith(('.zip', '.cbz')):
                src_path = os.path.join(root, file)
                dst_path = os.path.join(INPUT_DIR, file)
                
                # Handle duplicate filenames in input
                if os.path.exists(dst_path):
                    base, ext = os.path.splitext(file)
                    dst_path = os.path.join(INPUT_DIR, f"{base}_restored{ext}")
                
                try:
                    shutil.move(src_path, dst_path)
                    print(f" -> Moved: {file}")
                    count += 1
                except Exception as e:
                    print(f"Error moving {file}: {e}")
    
    print(f"   Moved {count} files.")

    # --- Step 2: Clean Library Folders ---
    print("\n[Step 3/5] Cleaning Library folders...")
    if os.path.exists(LIBRARY_DIR):
        shutil.rmtree(LIBRARY_DIR)
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    with open(os.path.join(LIBRARY_DIR, ".gitkeep"), 'w') as f:
        pass

    # --- Step 3: Delete Database ---
    print("\n[Step 4/5] Deleting Database & Thumbnails...")
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(" -> Database deleted.")
    
    # Clean Thumbnails
    for file in os.listdir(THUMBNAIL_DIR):
        if file != ".gitkeep":
            path = os.path.join(THUMBNAIL_DIR, file)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception as e:
                print(f"Error deleting {file}: {e}")
    print(" -> Thumbnails cleared.")

    # --- Step 4: Restart Docker ---
    print("\n[Step 5/5] Restarting Docker Containers...")
    run_docker_command(["docker-compose", "up", "-d"])

    print("\nSuccess! System has been fully reset.")

if __name__ == "__main__":
    reset_system()