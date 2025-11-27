from fastapi import FastAPI, Depends, HTTPException, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

# Import our local modules
from . import database, schemas
from .services import scanner, importer, reader

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

# Initialize Templates
templates = Jinja2Templates(directory="app/templates")

# --- API Endpoints ---

@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db)):
    # Fetch all galleries
    galleries = db.query(database.Gallery).all()
    # Render the library.html template
    return templates.TemplateResponse("library.html", {
        "request": request, 
        "galleries": galleries
    })

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
        
    image_data = scanner.get_cover_from_zip(str(staged_file.path))
    
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

@app.post("/api/import/{staged_id}")
def import_comic(staged_id: int, request: schemas.ImportRequest, db: Session = Depends(get_db)):
    """
    Moves a file from Staging to Library with the provided metadata.
    """
    try:
        gallery = importer.import_gallery(db, staged_id, request, DATA_DIR)
        return {"status": "success", "gallery_id": gallery.id, "title": gallery.title}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/staging")
def read_staging(request: Request):
    return templates.TemplateResponse("staging.html", {"request": request})

@app.get("/api/read/{gallery_id}/{page}")
def read_page(gallery_id: int, page: int, db: Session = Depends(get_db)):
    """
    Serves a single image from inside the gallery archive.
    """
    image_data = reader.get_page_image(db, gallery_id, page)
    return Response(content=image_data, media_type="image/jpeg")

@app.get("/reader/{gallery_id}")
def open_reader(gallery_id: int, request: Request, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    
    return templates.TemplateResponse("reader.html", {
        "request": request, 
        "gallery": gallery
    })

@app.post("/api/progress/{gallery_id}/{page}")
def update_progress(gallery_id: int, page: int, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    
    # Update Page
    # The IDE complains because it sees a 'Column' object, not an 'int'.
    # We add '# type: ignore' to silence this specific error.
    gallery.pages_read = page # type: ignore
    
    # Update Status Logic
    total = gallery.pages_total # type: ignore
    
    if total and page >= total: # type: ignore
        gallery.status = "Completed" # type: ignore
    elif page > 1:
        gallery.status = "Reading" # type: ignore
    else:
        gallery.status = "New" # type: ignore
        
    db.commit()
    return {"status": "updated", "current_status": gallery.status}