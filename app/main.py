import logging
import time
import shutil
import json
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

# Import our local modules
from . import database, schemas
from .services import scanner, importer, reader

# --- CONFIGURATION ---
DATA_DIR = os.getenv("DATA_DIR", "./data")
INPUT_DIR = os.path.join(DATA_DIR, "input")
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")
LOG_FILE = os.path.join(DATA_DIR, "logs", "server.log")

# Ensure Log Directory Exists immediately
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# --- SETUP LOGGING ---
# We configure this at the module level so it runs before the app starts
logging.basicConfig(
    filename=LOG_FILE, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True # Force usage of our settings
)
logger = logging.getLogger(__name__)

# Initialize App
app = FastAPI(title="Manga Server")

# --- MIDDLEWARE (Logs every request) ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    # Process the request
    response = await call_next(request)
    
    # Calculate duration
    process_time = (time.time() - start_time) * 1000
    
    # Log format: "GET /api/library - 200 OK - 15ms"
    # We skip logging the /api/logs endpoint itself to prevent infinite loops in the log viewer
    if "/api/logs" not in request.url.path:
        logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.2f}ms")
    
    return response

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
    logger.info("------------------------------------------------")
    logger.info(f"SERVER STARTED SUCCESSFULLY")
    logger.info(f"Monitoring Input Directory: {INPUT_DIR}")
    logger.info("------------------------------------------------")

# Mount Static Files (CSS, JS)
# We will create the 'static' folder later for the frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")

# Initialize Templates
templates = Jinja2Templates(directory="app/templates")

# --- API Endpoints ---

@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db)):
    """
    Serves the Library HTML page.
    """
    items = []
    
    # 1. Get Standalone Galleries
    standalone = db.query(database.Gallery).filter(database.Gallery.series_id == None).all()
    
    for g in standalone:
        items.append({
            "type": "gallery",
            "id": g.id,
            "title": g.title,
            "artist": g.artist,
            "status": g.status,
            "category": g.category.name if g.category else "",
            "thumb": f"/thumbnails/{g.id}.jpg",
            "series": "", 
            "tags": [t.name for t in g.tags],
            "description": g.description if g.description else "" # type: ignore
        })

    # 2. Get Series
    all_series = db.query(database.Series).all()
    
    for s in all_series:
        if not s.galleries:
            continue
            
        # Determine Series Thumbnail
        if s.thumbnail_url: # type: ignore
            thumb = s.thumbnail_url
        else:
            first = sorted(s.galleries, key=lambda x: (x.sort_order, x.id))[0]
            thumb = f"/thumbnails/{first.id}.jpg"
        
        # --- NEW MATH SECTION (Was missing here) ---
        total_count = len(s.galleries)
        read_count = sum(1 for g in s.galleries if g.status == "Completed")
            
        items.append({
            "type": "series",
            "id": s.id,
            "title": s.name,
            "artist": "Various", 
            "category": "Series",
            "thumb": thumb,
            
            # These are the fields the HTML needs:
            "count": total_count,
            "read_count": read_count, 
            "status": "Series", 
            
            "series": s.name,
            "tags": [],
            "description": s.description if s.description else "" # type: ignore
        })
        
    return templates.TemplateResponse("library.html", {
        "request": request, 
        "galleries": items
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
    Returns Galleries (if standalone) AND Series (as groups).
    Returns Dictionaries, not SQLAlchemy Objects.
    """
    items = []
    
    # 1. Get Standalone Galleries (series_id is None)
    standalone = db.query(database.Gallery).filter(database.Gallery.series_id == None).all()
    for g in standalone:
        items.append({
            "type": "gallery",
            "id": g.id,
            "title": g.title,
            "artist": g.artist,
            "status": g.status,
            "category": g.category.name if g.category else "",
            "thumb": f"/thumbnails/{g.id}.jpg",
            "series": "", 
            "tags": [t.name for t in g.tags], 
            "description": g.description if g.description else "" # type: ignore
        })

    # 2. Get Series
    all_series = db.query(database.Series).all()
    for s in all_series:
        if not s.galleries:
            continue
            
        # Determine Series Thumbnail
        if s.thumbnail_url: # type: ignore
            thumb = s.thumbnail_url
        else:
            # Use the first gallery's thumb
            first = sorted(s.galleries, key=lambda x: (x.sort_order, x.id))[0]
            thumb = f"/thumbnails/{first.id}.jpg"
        
        # --- NEW MATH SECTION ---
        total_count = len(s.galleries)
        # Count how many galleries in this series are marked 'Completed'
        read_count = sum(1 for g in s.galleries if g.status == "Completed")
            
        items.append({
            "type": "series",
            "id": s.id,
            "title": s.name,
            "artist": "Various", 
            "category": "Series",
            "thumb": thumb,
            
            # Send the raw numbers to the frontend
            "count": total_count,
            "read_count": read_count, 
            "status": "Series", # Placeholder
            
            "series": s.name,
            "tags": [],
            "description": s.description if s.description else "" # type: ignore
        })
        
    return items

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
        logger.warning(f"Update failed: Gallery ID {gallery_id} not found.")
        raise HTTPException(status_code=404, detail="Gallery not found")
    
    old_title = gallery.title
    
    # --- 1. FILE MOVEMENT LOGIC ---
    # We calculate the target path based on the NEW metadata (Artist + Series)
    try:
        # A. Sanitize New Artist
        safe_new_artist = "".join([c for c in request.artist if c.isalpha() or c.isdigit() or c in " -_"]).strip()
        
        # B. Sanitize New Series (if provided)
        safe_new_series = ""
        if request.series:
            safe_new_series = "".join([c for c in request.series if c.isalpha() or c.isdigit() or c in " -_"]).strip()

        # C. Construct Target Folder
        # Logic: Library / Artist / [Series] / File.zip
        if safe_new_series:
            new_folder = os.path.join(LIBRARY_DIR, safe_new_artist, safe_new_series)
        else:
            new_folder = os.path.join(LIBRARY_DIR, safe_new_artist)

        # D. Construct Target File Path
        filename = os.path.basename(gallery.path) # type: ignore
        new_path = os.path.join(new_folder, filename)
        
        # E. Compare & Move
        # If the path has changed (due to Artist change OR Series change), move it.
        if new_path != gallery.path:
            logger.info(f"Path change detected. Moving: '{gallery.path}' -> '{new_path}'")
            
            # Create new directory
            os.makedirs(new_folder, exist_ok=True)
            
            # Move the file
            shutil.move(gallery.path, new_path) # type: ignore
            
            # Save old path for cleanup
            old_path = gallery.path
            
            # Update DB
            gallery.path = new_path # type: ignore
            
            # Cleanup: Delete old folder if empty
            # We check the folder the file USED to be in
            old_dir = os.path.dirname(old_path) # type: ignore
            try:
                if os.path.exists(old_dir) and not os.listdir(old_dir):
                    os.rmdir(old_dir)
                    logger.info(f"Deleted empty folder: {old_dir}")
                    
                    # Optional: If we just deleted a Series folder, check if the Artist folder above it is empty too
                    parent_dir = os.path.dirname(old_dir)
                    if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                        os.rmdir(parent_dir)
                        logger.info(f"Deleted empty parent folder: {parent_dir}")
            except Exception as e:
                logger.warning(f"Cleanup warning: {e}")

    except Exception as e:
        logger.error(f"Failed to move file during metadata update: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to move file: {e}")

    # --- 2. METADATA UPDATES ---

    # Update basic fields
    gallery.title = request.title # type: ignore
    gallery.artist = request.artist # type: ignore
    gallery.description = request.description # type: ignore
    gallery.reading_direction = request.direction # type: ignore
    
    # Update Series
    if request.series:
        series = db.query(database.Series).filter(database.Series.name == request.series).first()
        if not series:
            series = database.Series(name=request.series)
            db.add(series)
            db.flush()
        gallery.series_id = series.id
    else:
        gallery.series_id = None # type: ignore

    # Update Category
    if request.category:
        cat = db.query(database.Category).filter(database.Category.name == request.category).first()
        if not cat:
            cat = database.Category(name=request.category)
            db.add(cat)
            db.flush()
        gallery.category_id = cat.id
    else:
        gallery.category_id = None # type: ignore

    # Update Tags
    gallery.tags.clear()
    for tag_name in request.tags:
        tag = db.query(database.Tag).filter(database.Tag.name == tag_name).first()
        if not tag:
            tag = database.Tag(name=tag_name)
            db.add(tag)
        gallery.tags.append(tag)

    db.commit()
    logger.info(f"Metadata updated for ID {gallery_id}: '{old_title}' -> '{gallery.title}'")
    return {"status": "success"}

# --- SETTINGS API ---

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    settings_list = db.query(database.Settings).all()
    settings_dict = {s.key: s.value for s in settings_list}
    
    # Defaults
    if "default_direction" not in settings_dict:
        settings_dict["default_direction"] = "LTR" # type: ignore
    
    # NEW: Default for the toggle
    if "show_uncategorized" not in settings_dict:
        settings_dict["show_uncategorized"] = "false" # type: ignore
        
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

# --- CATEGORY MANAGEMENT API ---

@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Returns a list of categories with the count of galleries in each.
    """
    categories = db.query(database.Category).all()
    result = []
    for cat in categories:
        result.append({
            "id": cat.id, 
            "name": cat.name, 
            "count": len(cat.galleries) # SQLAlchemy relationship makes this easy
        })
    return result

@app.post("/api/categories")
def create_category(payload: dict, db: Session = Depends(get_db)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    
    existing = db.query(database.Category).filter(database.Category.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    
    new_cat = database.Category(name=name)
    db.add(new_cat)
    db.commit()
    return {"status": "created", "id": new_cat.id, "name": new_cat.name}

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int, force: bool = False, db: Session = Depends(get_db)):
    cat = db.query(database.Category).filter(database.Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Check if empty
    if len(cat.galleries) > 0 and not force:
        return {
            "status": "conflict", 
            "message": f"This category contains {len(cat.galleries)} galleries.",
            "count": len(cat.galleries)
        }
    
    # If force is True, or empty, we delete.
    # Note: Because of SQLAlchemy relationships, we need to ensure we don't delete the galleries, just the link.
    # Setting the relationship to None happens automatically if we don't use 'cascade=delete'.
    # But let's be explicit to be safe:
    for gallery in cat.galleries:
        gallery.category_id = None
        
    db.delete(cat)
    db.commit()
    return {"status": "deleted"}

@app.delete("/api/logs")
def clear_logs():
    """Clears the log file content"""
    if os.path.exists(LOG_FILE):
        # Open in 'w' mode to truncate/wipe the file
        with open(LOG_FILE, 'w') as f:
            pass 
            
        # Add a fresh log entry so it's not totally empty
        logger.info("Logs cleared by user.")
        
    return {"status": "cleared"}

# --- BACKUP & RESTORE API ---

@app.get("/api/backup")
def backup_database(db: Session = Depends(get_db)):
    """
    Exports all database tables to a JSON structure.
    """
    data = {
        "timestamp": str(datetime.now()),
        "version": "1.0",
        "categories": [],
        "series": [],
        "tags": [],
        "galleries": [],
        "settings": []
    }

    # 1. Export Categories
    for c in db.query(database.Category).all():
        data["categories"].append({"id": c.id, "name": c.name})

    # 2. Export Series
    for s in db.query(database.Series).all():
        data["series"].append({"id": s.id, "name": s.name, "description": s.description})

    # 3. Export Tags
    for t in db.query(database.Tag).all():
        data["tags"].append({"id": t.id, "name": t.name})

    # 4. Export Settings
    for s in db.query(database.Settings).all():
        data["settings"].append({"key": s.key, "value": s.value})

    # 5. Export Galleries
    # We need to manually construct this to handle relationships (tags)
    for g in db.query(database.Gallery).all():
        g_data = {
            "id": g.id,
            "filename": g.filename,
            "path": g.path,
            "title": g.title,
            "artist": g.artist,
            "status": g.status,
            "pages_read": g.pages_read,
            "pages_total": g.pages_total,
            "reading_direction": g.reading_direction,
            "series_id": g.series_id,
            "category_id": g.category_id,
            "description": g.description,
            "tag_names": [t.name for t in g.tags] # Store names to link back later
        }
        data["galleries"].append(g_data)

    return data

@app.post("/api/restore")
async def restore_database(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Wipes the DB and restores from JSON.
    """
    try:
        content = await file.read()
        data = json.loads(content)
        
        # 1. WIPE TABLES (Order matters for Foreign Keys)
        # Clear relationships first
        db.query(database.gallery_tags).delete()
        db.query(database.Gallery).delete()
        db.query(database.Series).delete()
        db.query(database.Category).delete()
        db.query(database.Tag).delete()
        db.query(database.Settings).delete()
        db.commit()

        # 2. RESTORE (Keep original IDs to preserve file links)
        
        # Categories
        for c in data.get("categories", []):
            db.add(database.Category(id=c["id"], name=c["name"]))
        
        # Series
        for s in data.get("series", []):
            db.add(database.Series(id=s["id"], name=s["name"], description=s.get("description")))
            
        # Tags
        tag_map = {} # Cache for quick lookup during gallery restore
        for t in data.get("tags", []):
            new_tag = database.Tag(id=t["id"], name=t["name"])
            db.add(new_tag)
            tag_map[t["name"]] = new_tag
            
        # Settings
        for s in data.get("settings", []):
            db.add(database.Settings(key=s["key"], value=s["value"]))
            
        db.commit() # Commit base tables before galleries
        
        # Galleries
        for g in data.get("galleries", []):
            new_gallery = database.Gallery(
                id=g["id"],
                filename=g["filename"],
                path=g["path"],
                title=g["title"],
                artist=g["artist"],
                status=g["status"],
                pages_read=g.get("pages_read", 0),
                pages_total=g.get("pages_total", 0),
                reading_direction=g.get("reading_direction", "LTR"),
                series_id=g["series_id"],
                category_id=g["category_id"],
                description=g.get("description")
            )
            
            # Re-link Tags
            for t_name in g.get("tag_names", []):
                if t_name in tag_map:
                    new_gallery.tags.append(tag_map[t_name])
            
            db.add(new_gallery)
            
        db.commit()
        logger.info("Database restored successfully from backup.")
        return {"status": "success", "message": "Database restored."}

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")
    
    # --- UPLOAD API ---
@app.get("/upload")
def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/api/upload")
async def upload_gallery(file: UploadFile = File(...)):
    """
    Receives a file and streams it to the Input folder.
    """
    try:
        # Security check: Ensure it's a zip/cbz
        if not file.filename.lower().endswith(('.zip', '.cbz')): # type: ignore
            raise HTTPException(status_code=400, detail="Only .zip and .cbz files are allowed.")
        
        file_location = os.path.join(INPUT_DIR, file.filename) # type: ignore
        
        # Write file to disk in chunks (memory efficient)
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
            
        return {"filename": file.filename, "status": "success"}
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    
    # --- SERIES API ---

@app.get("/series/{series_id}")
def view_series_page(series_id: int, request: Request, db: Session = Depends(get_db)):
    series = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
        
    # Sort galleries by our new sort_order column
    galleries = sorted(series.galleries, key=lambda x: (x.sort_order, x.id))
    
    return templates.TemplateResponse("series.html", {
        "request": request, 
        "series": series, 
        "galleries": galleries
    })

@app.post("/api/series/{series_id}/update")
def update_series(series_id: int, payload: dict, db: Session = Depends(get_db)):
    series = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    if "name" in payload:
        series.name = payload["name"]
        
    # NEW: Handle Thumbnail Update
    if "thumbnail_url" in payload:
        series.thumbnail_url = payload["thumbnail_url"]
    
    if "order" in payload:
        for idx, gal_id in enumerate(payload["order"]):
            gal = next((g for g in series.galleries if g.id == int(gal_id)), None)
            if gal:
                gal.sort_order = idx + 1 
                
    db.commit()
    return {"status": "success"}