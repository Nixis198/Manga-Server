import os
import zipfile
from sqlalchemy.orm import Session
from ..database import StagedFile, SessionLocal

def scan_input_directory(input_dir: str):
    """
    Scans the input directory for .zip files and syncs them with the StagedFile DB table.
    """
    db: Session = SessionLocal()
    try:
        # 1. Get list of physical files in Input folder
        physical_files = []
        if os.path.exists(input_dir):
            for f in os.listdir(input_dir):
                if f.lower().endswith(".zip") or f.lower().endswith(".cbz"):
                    physical_files.append(f)
        
        # 2. Get list of files currently in DB
        db_files = db.query(StagedFile).all()
        db_filenames = {f.filename: f for f in db_files}

        # 3. Add new files to DB
        new_files_count = 0
        for filename in physical_files:
            if filename not in db_filenames:
                # Try to guess title/artist from filename (simple guess)
                # Format assumed: [Artist] Title.zip
                suggested_artist = None
                suggested_title = os.path.splitext(filename)[0]
                
                if "]" in filename and "[" in filename:
                    try:
                        # Extract content inside brackets as artist
                        start = filename.find("[") + 1
                        end = filename.find("]")
                        suggested_artist = filename[start:end]
                        # Title is the rest, stripped of brackets
                        suggested_title = filename[end+1:].replace(".zip", "").replace(".cbz", "").strip()
                    except:
                        pass # Fallback to filename as title

                new_stage = StagedFile(
                    filename=filename,
                    path=os.path.join(input_dir, filename),
                    suggested_title=suggested_title,
                    suggested_artist=suggested_artist
                )
                db.add(new_stage)
                new_files_count += 1
        
        # 4. Remove DB entries if file no longer exists (User deleted it manually)
        for db_file in db_files:
            if db_file.filename not in physical_files:
                db.delete(db_file)

        db.commit()
        return {"added": new_files_count, "total_staged": len(physical_files)}

    except Exception as e:
        print(f"Error scanning input directory: {e}")
        return {"error": str(e)}
    finally:
        db.close()

def get_cover_from_zip(zip_path: str):
    """
    Helper to extract the first image from a ZIP for previewing in the Staging UI.
    Returns bytes of the image or None.
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            # Get list of files, filter for images, sort by name
            files = sorted([
                f for f in z.namelist() 
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
            ])
            if files:
                return z.read(files[0])
    except Exception as e:
        print(f"Error reading zip {zip_path}: {e}")
    return None