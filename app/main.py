from fastapi import FastAPI, Depends, HTTPException, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os
import logging

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

LOG_FILE = os.path.join(DATA_DIR, "logs", "server.log")

@app.on_event("startup")
async def startup_event():
    # 1. Create necessary directories
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # 2. Setup Logging
    # This captures print statements and errors to the file
    logging.basicConfig(
        filename=LOG_FILE, 
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s',
        force=True
    )
    
    # 3. Initialize Database
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
    galleries = db.query(database.Gallery).all()
    # We return the data; SQLAlchemy relationships handle the category/series names
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

@app.post("/api/gallery/{gallery_id}/update")
def update_gallery_metadata(gallery_id: int, request: schemas.ImportRequest, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    
    # 1. Update basic fields
    gallery.title = request.title # type: ignore
    gallery.artist = request.artist # type: ignore
    gallery.description = request.description # type: ignore
    gallery.reading_direction = request.direction # type: ignore
    
    # 2. Update Series
    if request.series:
        series = db.query(database.Series).filter(database.Series.name == request.series).first()
        if not series:
            series = database.Series(name=request.series)
            db.add(series)
            db.flush()
        gallery.series_id = series.id
    else:
        gallery.series_id = None # type: ignore

    # 3. Update Category
    if request.category:
        cat = db.query(database.Category).filter(database.Category.name == request.category).first()
        if not cat:
            cat = database.Category(name=request.category)
            db.add(cat)
            db.flush()
        gallery.category_id = cat.id
    else:
        gallery.category_id = None # type: ignore

    # 4. Update Tags (Clear and Re-add)
    gallery.tags.clear()
    for tag_name in request.tags:
        tag = db.query(database.Tag).filter(database.Tag.name == tag_name).first()
        if not tag:
            tag = database.Tag(name=tag_name)
            db.add(tag)
        gallery.tags.append(tag)

    db.commit()
    return {"status": "success"}

# --- SETTINGS API ---

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    # Convert DB rows (Key/Value) into a simple JSON object
    settings_list = db.query(database.Settings).all()
    settings_dict = {s.key: s.value for s in settings_list}
    
    # Set defaults if keys don't exist
    if "default_direction" not in settings_dict:
        settings_dict["default_direction"] = "LTR" # type: ignore
        
    return settings_dict

@app.post("/api/settings")
def save_settings(payload: dict, db: Session = Depends(get_db)):
    for key, value in payload.items():
        setting = db.query(database.Settings).filter(database.Settings.key == key).first()
        if not setting:
            setting = database.Settings(key=key, value=str(value))
            db.add(setting)
        else:
            setting.value = str(value) # type: ignore
    db.commit()
    logging.info("Settings updated by user.")
    return {"status": "saved"}

# --- LOGS API ---

@app.get("/api/logs")
def get_logs():
    """Reads the last 100 lines of the log file"""
    if not os.path.exists(LOG_FILE):
        return {"logs": "Log file not created yet."}
    
    try:
        with open(LOG_FILE, "r") as f:
            # Simple tail implementation
            lines = f.readlines()
            last_lines = lines[-100:] # Get last 100
            return {"logs": "".join(last_lines)}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}

# --- ROUTE FOR THE PAGE ---
@app.get("/settings")
def read_settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})