import json
import os

def migrate_backup():
    input_filename = "backup.json"
    output_filename = "backup_updated.json"

    # 1. Check if file exists
    if not os.path.exists(input_filename):
        print(f"Error: Could not find '{input_filename}'.")
        print("Please place your database backup in this folder and rename it to 'backup.json'.")
        return

    print(f"Reading {input_filename}...")

    try:
        with open(input_filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 2. Locate the galleries list
        if "galleries" not in data:
            print("Error: Invalid backup format. Could not find 'galleries' list.")
            return

        galleries = data["galleries"]
        count = 0

        # 3. Iterate and add the field
        for gallery in galleries:
            # We check if it's missing to avoid overwriting if you ran this twice
            if "source_url" not in gallery:
                gallery["source_url"] = "" # Initialize as empty string
                count += 1

        # 4. Save the new file
        print(f"Migrated {count} galleries.")
        print(f"Writing to {output_filename}...")

        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

        print("Done! You can now use 'backup_updated.json' to restore after updating the server code.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    migrate_backup()