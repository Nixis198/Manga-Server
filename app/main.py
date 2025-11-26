from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import os

# Import our local modules
from . import database
from .services import scanner

# Configuration
DATA_DIR = os.getenv("DATA_DIR", "./data")
INPUT_DIR = os.path.join(DATA_DIR, "input")
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")

# Initialize App
app = FastAPI(title="Manga Server")

# Dependency to get DB session
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # 1. Create necessary directories
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    
    # 2. Initialize Database
    database.init_db()
    print(f"Server started. Monitoring {INPUT_DIR}")

# Mount Static Files (CSS, JS)
# We will create the 'static' folder later for the frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")

# --- API Endpoints ---

@app.get("/")
def read_root():
    return {
        "status": "Manga Server is running", 
        "endpoints": ["/api/scan", "/api/staged", "/api/library"]
    }

@app.post("/api/scan")
def scan_input_folder():
    """
    Triggers a scan of the 'Input' folder.
    Returns the count of new files found and total staged files.
    """
    result = scanner.scan_input_directory(INPUT_DIR)
    return result

@app.get("/api/staged")
def get_staged_files(db: Session = Depends(get_db)):
    """
    Returns a list of all files currently in the staging area.
    """
    files = db.query(database.StagedFile).all()
    return files

@app.get("/api/staged/{file_id}/cover")
def get_staged_cover(file_id: int, db: Session = Depends(get_db)):
    """
    Extracts the first image from a staged ZIP file and serves it directly.
    This allows the UI to show a preview without extracting the whole comic.
    """
    staged_file = db.query(database.StagedFile).filter(database.StagedFile.id == file_id).first()
    
    if not staged_file:
        raise HTTPException(status_code=404, detail="File not found")
        
    image_data = scanner.get_cover_from_zip(staged_file.path)
    
    if image_data:
        # We assume JPEG for now, but browsers are smart enough to handle PNGs sent as image/jpeg usually.
        # Ideally, we would detect the mime type, but this is sufficient for a prototype.
        return Response(content=image_data, media_type="image/jpeg")
    else:
        raise HTTPException(status_code=404, detail="No images found in archive")

@app.get("/api/library")
def get_library(db: Session = Depends(get_db)):
    """
    Returns the main library galleries (Already imported).
    """
    galleries = db.query(database.Gallery).all()
    return galleries