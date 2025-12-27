import os
import shutil
import logging
import zipfile
import io
import threading
import time
import json
import re
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

# Import our local modules
from . import database, schemas
from .services import scanner, importer, reader
from .plugins import manager

# --- CONFIGURATION ---
DATA_DIR = os.getenv("DATA_DIR", "./data")
INPUT_DIR = os.path.join(DATA_DIR, "input")
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")
LOG_FILE = os.path.join(DATA_DIR, "logs", "server.log")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

# Ensure Log Directory Exists immediately
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# --- SETUP LOGGING ---
logging.basicConfig(
    filename=LOG_FILE, 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)
logger = logging.getLogger(__name__)

# Initialize App
app = FastAPI(title="Manga Server")

# --- MIDDLEWARE ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
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

# --- HELPERS ---

def sanitize_filename(name):
    """ Cleans strings to be safe for folder/file names """
    if not name: return "Unknown"
    s = str(name).strip().replace('"', '').replace("'", "")
    s = re.sub(r'[<>:"/\\|?*]', '', s) # Remove forbidden filesystem chars
    return s.strip() or "Unknown"

def cleanup_parent_folders(file_path):
    """ Recursively deletes empty parent folders up to the Library root """
    try:
        parent_dir = os.path.dirname(file_path)
        # Security check: Ensure we are inside the DATA directory
        if os.path.commonpath([parent_dir, os.path.abspath(DATA_DIR)]) == os.path.abspath(DATA_DIR):
            if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                os.rmdir(parent_dir)
                # Try grandparent
                grandparent = os.path.dirname(parent_dir)
                if os.path.commonpath([grandparent, os.path.abspath(DATA_DIR)]) == os.path.abspath(DATA_DIR):
                    if os.path.exists(grandparent) and not os.listdir(grandparent):
                        os.rmdir(grandparent)
    except Exception as e:
        logger.error(f"Cleanup failed for {file_path}: {e}")

def move_gallery_file(gallery, new_artist, new_series=None):
    """ Moves a gallery file to a new structure based on metadata """
    try:
        # Construct New Path structure: Library / Artist / [Series] / Filename
        safe_artist = sanitize_filename(new_artist)
        target_dir = os.path.join(LIBRARY_DIR, safe_artist)
        
        if new_series:
            safe_series = sanitize_filename(new_series)
            target_dir = os.path.join(target_dir, safe_series)
            
        current_path = gallery.path
        filename = os.path.basename(current_path)
        new_path = os.path.join(target_dir, filename)
        
        # Move only if path is different
        if os.path.abspath(current_path) != os.path.abspath(new_path):
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            if os.path.exists(current_path):
                shutil.move(current_path, new_path)
                logger.info(f"Moved file: {current_path} -> {new_path}")
                
                # Update DB Object (Caller must commit)
                gallery.path = new_path
                
                # Cleanup old folders
                cleanup_parent_folders(current_path)
            else:
                logger.warning(f"File not found for move: {current_path}")
                
    except Exception as e:
        logger.error(f"Failed to move file for gallery {gallery.id}: {e}")

def get_series_cover(series):
    if not series.galleries: return ""
    sorted_gals = sorted(series.galleries, key=lambda x: (x.sort_order, x.id))
    if series.thumbnail_url == "__reading__":
        reading_gal = next((g for g in sorted_gals if g.status == "Reading"), None)
        if reading_gal: return f"/thumbnails/{reading_gal.id}.jpg"
        return f"/thumbnails/{sorted_gals[0].id}.jpg"
    if series.thumbnail_url: return series.thumbnail_url
    return f"/thumbnails/{sorted_gals[0].id}.jpg"

def get_series_category_name(series):
    """ Calculates the inherited category for a series based on its contents """
    if not series.galleries: return None
    for g in series.galleries:
        if g.category: return g.category.name
    return None

def get_series_artist_name(series):
    """ Calculates the inherited artist. Returns 'Various' if mixed. """
    if not series.galleries: return "Unknown"
    
    artists = set()
    for g in series.galleries:
        if g.artist: artists.add(g.artist)
    
    if len(artists) == 0: return "Unknown"
    if len(artists) == 1: return list(artists)[0]
    return "Various"

def build_search_string(title, artist, extra_list=None):
    terms = [title, artist]
    if extra_list: terms.extend(extra_list)
    return " ".join([str(t).lower() for t in terms if t])

def perform_auto_backup(db: Session):
    try:
        data = backup_db(db)
        filename = f"autobackup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
        filepath = os.path.join(BACKUP_DIR, filename)
        with open(filepath, "w") as f: json.dump(data, f)
        s = db.query(database.Settings).filter(database.Settings.key == "last_backup_timestamp").first()
        now_ts = str(int(time.time()))
        if not s: db.add(database.Settings(key="last_backup_timestamp", value=now_ts))
        else: s.value = now_ts # type: ignore
        db.commit()
    except Exception as e: logger.error(f"Auto-backup failed: {e}")

def backup_scheduler_loop():
    while True:
        time.sleep(3600)
        try:
            db = database.SessionLocal()
            s_enabled = db.query(database.Settings).filter(database.Settings.key == "auto_backup_enabled").first()
            s_freq = db.query(database.Settings).filter(database.Settings.key == "auto_backup_frequency").first()
            s_last = db.query(database.Settings).filter(database.Settings.key == "last_backup_timestamp").first()
            
            enabled = s_enabled.value == "true" if s_enabled else False
            days_freq = int(s_freq.value) if s_freq and s_freq.value.isdigit() else 7 # type: ignore
            last_ts = int(s_last.value) if s_last and s_last.value.isdigit() else 0 # type: ignore
            
            if enabled: # type: ignore
                if (int(time.time()) - last_ts) > (days_freq * 86400):
                    perform_auto_backup(db)
            db.close()
        except Exception: pass

@app.on_event("startup")
async def startup_event():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    database.init_db()
    update_template_globals()
    threading.Thread(target=backup_scheduler_loop, daemon=True).start()
    logger.info("Server Started Successfully")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")
templates = Jinja2Templates(directory="app/templates")

def update_template_globals():
    db = database.SessionLocal()
    try:
        setting = db.query(database.Settings).filter(database.Settings.key == "server_name").first()
        name = setting.value if setting else "Manga Server"
        templates.env.globals["server_name"] = name
    finally:
        db.close()

# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse("library.html", {"request": request})

# --- ADDED STATS PAGES ---
@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", {"request": request})

@app.get("/api/stats")
def get_stats_data(db: Session = Depends(get_db)):
    # 1. Basic Counts
    total_gals = db.query(database.Gallery).count()
    total_series = db.query(database.Series).count()
    total_artists = db.query(database.Gallery.artist).distinct().count()
    
    # 2. Page Progress
    pages_total = db.query(func.sum(database.Gallery.pages_total)).scalar() or 0
    pages_read = db.query(func.sum(database.Gallery.pages_read)).scalar() or 0
    global_prog = int((pages_read / pages_total * 100) if pages_total > 0 else 0)

    # 3. Status Distribution
    status_counts = db.query(database.Gallery.status, func.count(database.Gallery.id)).group_by(database.Gallery.status).all()
    status_map = {s: c for s, c in status_counts}

    # 4. Category Distribution
    cat_counts = db.query(database.Category.name, func.count(database.Gallery.id))\
                   .outerjoin(database.Category, database.Gallery.category_id == database.Category.id)\
                   .group_by(database.Category.name).all()
    
    cat_map = {}
    for name, count in cat_counts:
        cat_map[name if name else "Uncategorized"] = count

    # 5. Top Artists (Top 10)
    artists = db.query(database.Gallery.artist, func.count(database.Gallery.id))\
                .filter(database.Gallery.artist != None, database.Gallery.artist != "")\
                .group_by(database.Gallery.artist)\
                .order_by(desc(func.count(database.Gallery.id)))\
                .limit(10).all()
    
    top_artists = [{"name": a, "count": c} for a, c in artists]

    # 6. Top Tags (Top 10)
    tags = db.query(database.Tag.name, func.count(database.gallery_tags.c.gallery_id))\
             .join(database.gallery_tags)\
             .group_by(database.Tag.id)\
             .order_by(desc(func.count(database.gallery_tags.c.gallery_id)))\
             .limit(10).all()
             
    top_tags = [{"name": t, "count": c} for t, c in tags]

    return {
        "total_galleries": total_gals,
        "total_series": total_series,
        "total_artists": total_artists,
        "total_pages": pages_total,
        "global_progress": global_prog,
        "status_distribution": status_map,
        "category_distribution": cat_map,
        "top_artists": top_artists,
        "top_tags": top_tags
    }

@app.get("/api/library")
def get_library(
    search: str = "", 
    category: str = "all", 
    filter_type: str = "all", 
    sort: str = "title_asc",
    db: Session = Depends(get_db)
):
    items = []
    search = search.lower()
    
    # 1. BOOKS
    if filter_type in ["all", "books"]:
        g_query = db.query(database.Gallery).filter(database.Gallery.series_id == None)
        if category != "all" and category != "uncategorized":
            if category.isdigit(): g_query = g_query.filter(database.Gallery.category_id == int(category))
        elif category == "uncategorized":
            g_query = g_query.filter(database.Gallery.category_id == None)
        
        for g in g_query.all():
            s_str = build_search_string(g.title, g.artist)
            if search and search not in s_str: continue
            items.append({
                "type": "gallery", "id": g.id, "title": g.title, "artist": g.artist,
                "status": g.status, "pages_read": g.pages_read, "pages_total": g.pages_total,
                "category": g.category.name if g.category else "", "thumb": f"/thumbnails/{g.id}.jpg",
                "series": "", "tags": [t.name for t in g.tags], "description": g.description or "", "created_at": g.id,
                "source_url": g.source_url or ""
            })

    # 2. SERIES
    if filter_type in ["all", "series"]:
        s_query = db.query(database.Series)
        
        # Category Filter (via inheritance)
        if category != "all":
            s_query = s_query.join(database.Gallery)
            if category == "uncategorized":
                s_query = s_query.filter(database.Gallery.category_id == None)
            elif category.isdigit():
                s_query = s_query.filter(database.Gallery.category_id == int(category))
            s_query = s_query.distinct()
            
        for s in s_query.all():
            if not s.galleries: continue
            
            child_tags = []
            child_titles = []
            child_artists = []
            
            for g in s.galleries:
                child_titles.append(g.title)
                if g.artist: child_artists.append(g.artist)
                for t in g.tags: child_tags.append(t.name)
            
            search_blob = build_search_string(s.name, s.artist, child_titles + child_tags + child_artists)
            
            if search and search not in search_blob: continue

            read_count = sum(1 for g in s.galleries if g.status == "Completed")
            any_progress = any(g.status != "New" for g in s.galleries)
            
            # INHERITANCE
            cat_name = get_series_category_name(s) or "Series"
            art_name = get_series_artist_name(s)

            items.append({
                "type": "series", "id": s.id, "title": s.name, 
                "artist": art_name,
                "status": f"{len(s.galleries)} Items", 
                "category": cat_name, 
                "thumb": get_series_cover(s), "count": len(s.galleries), "read_count": read_count,
                "is_new": not any_progress, "series": s.name, "tags": sorted(list(set(child_tags))),
                "description": s.description or "", "created_at": s.id
            })

    # SORTING LOGIC
    if sort == "title_desc":
        items.sort(key=lambda x: x['title'].lower(), reverse=True)
    elif sort == "artist_asc":
        items.sort(key=lambda x: (x['artist'] or "").lower())
    elif sort == "artist_desc":
        items.sort(key=lambda x: (x['artist'] or "").lower(), reverse=True)
    else: # title_asc (default)
        items.sort(key=lambda x: x['title'].lower())

    return {"items": items, "total": len(items)}

@app.get("/series/{series_id}", response_class=HTMLResponse)
def view_series_page(series_id: int, request: Request, db: Session = Depends(get_db)):
    series = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not series: raise HTTPException(404, "Series not found")
    galleries = sorted(series.galleries, key=lambda x: (x.sort_order, x.id))
    
    display_tags = []
    for g in galleries:
        for t in g.tags: display_tags.append(t.name)
        
    series_category = get_series_category_name(series)
    series_artist = get_series_artist_name(series)
    
    return templates.TemplateResponse("series.html", {
        "request": request, "series": series, "galleries": galleries,
        "cover_url": get_series_cover(series), "display_tags": sorted(list(set(display_tags))),
        "series_category": series_category,
        "series_artist": series_artist
    })

@app.get("/reader/{gallery_id}", response_class=HTMLResponse)
def open_reader(gallery_id: int, request: Request, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery: raise HTTPException(404, "Gallery not found")
    if gallery.status == "New": # type: ignore
        gallery.status = "Reading" # type: ignore
        db.commit()
    
    # FETCH PRELOAD SETTING
    s = db.query(database.Settings).filter(database.Settings.key == "preload_pages").first()
    preload_count = int(s.value) if s else 2 # type: ignore
    
    return templates.TemplateResponse("reader.html", {
        "request": request, 
        "gallery": gallery,
        "preload_count": preload_count 
    })

@app.get("/staging", response_class=HTMLResponse)
def read_staging(request: Request): return templates.TemplateResponse("staging.html", {"request": request})
@app.get("/settings", response_class=HTMLResponse)
def read_settings_page(request: Request): return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request): return templates.TemplateResponse("upload.html", {"request": request})

# --- ACTIONS ---

@app.post("/api/scan")
def scan_input_folder(): return scanner.scan_input_directory(INPUT_DIR)

@app.get("/api/staged")
def get_staged_files(db: Session = Depends(get_db)): return db.query(database.StagedFile).all()

@app.get("/api/staged/{file_id}/peek")
def peek_staged_file(file_id: int, db: Session = Depends(get_db)):
    staged = db.query(database.StagedFile).filter(database.StagedFile.id == file_id).first()
    if not staged: raise HTTPException(404, "Not found")
    try:
        with zipfile.ZipFile(str(staged.path), 'r') as zf:
            file_list = zf.namelist()
            images = [f for f in file_list if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            images.sort()
            if images: return {"filename": os.path.basename(images[0])}
    except Exception: pass
    return {"filename": ""}

@app.get("/api/staged/{file_id}/cover")
def get_staged_cover_img(file_id: int, db: Session = Depends(get_db)):
    staged = db.query(database.StagedFile).filter(database.StagedFile.id == file_id).first()
    if not staged: return Response(status_code=404)
    img = scanner.get_cover_from_zip(str(staged.path))
    if img: return Response(content=img, media_type="image/jpeg")
    return Response(status_code=404)

@app.post("/api/import/{staged_id}")
def import_comic(staged_id: int, request: schemas.ImportRequest, db: Session = Depends(get_db)):
    try:
        gallery = importer.import_gallery(db, staged_id, request, DATA_DIR)
        return {"status": "success", "gallery_id": gallery.id}
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.get("/api/read/{gallery_id}/{page}")
def read_page_image(gallery_id: int, page: int, db: Session = Depends(get_db)):
    image_data = reader.get_page_image(db, gallery_id, page)
    return Response(content=image_data, media_type="image/jpeg")

@app.post("/api/progress/{gallery_id}/{page}")
def update_progress(gallery_id: int, page: int, db: Session = Depends(get_db)):
    g = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not g: raise HTTPException(404, "Not found")
    g.pages_read = page # type: ignore
    if g.pages_total and page >= g.pages_total: g.status = "Completed" # type: ignore
    elif page > 1: g.status = "Reading" # type: ignore
    else: g.status = "New" # type: ignore
    db.commit()
    return {"status": "updated"}

# --- UPDATE METADATA (WITH FILE MOVING) ---

@app.post("/api/gallery/{gallery_id}/update")
def update_gallery_metadata(gallery_id: int, request: schemas.ImportRequest, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery: raise HTTPException(404, "Gallery not found")
    
    # 1. Update basic fields
    gallery.title = request.title # type: ignore
    gallery.artist = request.artist # type: ignore
    gallery.description = request.description # type: ignore
    if request.direction: gallery.reading_direction = request.direction # type: ignore
    
    # 2. Handle Series Link
    if request.series:
        s = db.query(database.Series).filter(database.Series.name == request.series).first()
        if not s:
            s = database.Series(name=request.series)
            db.add(s)
            db.flush()
        gallery.series_id = s.id
    else:
        gallery.series_id = None # type: ignore

    # 3. Handle Category
    if request.category:
        c = db.query(database.Category).filter(database.Category.name == request.category).first()
        if not c:
            c = database.Category(name=request.category)
            db.add(c)
            db.flush()
        gallery.category_id = c.id
    else:
        gallery.category_id = None # type: ignore

    # 4. Handle Tags
    gallery.tags.clear()
    for t_name in request.tags:
        t_name = t_name.strip()
        if not t_name: continue
        t = db.query(database.Tag).filter(database.Tag.name == t_name).first()
        if not t:
            t = database.Tag(name=t_name)
            db.add(t)
        gallery.tags.append(t)
        
    # 5. MOVE FILE ON DISK
    new_artist = gallery.artist
    new_series = request.series if request.series else None
    move_gallery_file(gallery, new_artist, new_series)

    db.commit()
    return {"status": "success"}

@app.post("/api/series/{series_id}/update")
def update_series_metadata(series_id: int, payload: dict, db: Session = Depends(get_db)):
    s = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not s: raise HTTPException(404, "Series not found")
    
    if "name" in payload: s.name = payload["name"]
    if "thumbnail_url" in payload: s.thumbnail_url = payload["thumbnail_url"]
    if "description" in payload: s.description = payload["description"]
    
    if "tags" in payload:
        s.tags.clear()
        for t_name in payload["tags"]:
            t_name = t_name.strip()
            if not t_name: continue
            t = db.query(database.Tag).filter(database.Tag.name == t_name).first()
            if not t:
                t = database.Tag(name=t_name)
                db.add(t)
            s.tags.append(t)

    if "order" in payload:
        for idx, g_id in enumerate(payload["order"]):
            g = db.query(database.Gallery).filter(database.Gallery.id == g_id).first()
            if g and g.series_id == s.id: g.sort_order = idx + 1 # type: ignore

    # 5. BATCH MOVE FILES
    if "name" in payload:
        new_series_name = s.name
        for g in s.galleries:
            move_gallery_file(g, g.artist, new_series_name)

    db.commit()
    return {"status": "success"}

# --- DELETE / DOWNLOAD ---

@app.get("/api/download/{gallery_id}")
def download_gallery(gallery_id: int, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery or not os.path.exists(gallery.path): raise HTTPException(404, "File not found") # type: ignore
    return FileResponse(path=gallery.path, filename=os.path.basename(gallery.path), media_type='application/octet-stream') # type: ignore

@app.get("/api/download/series/{series_id}")
def download_series(series_id: int, db: Session = Depends(get_db)):
    series = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not series: raise HTTPException(404, "Series not found")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        for gallery in series.galleries:
            if os.path.exists(gallery.path): zf.write(gallery.path, arcname=gallery.filename)
    zip_buffer.seek(0)
    return StreamingResponse(iter([zip_buffer.getvalue()]), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={series.name}.zip"})

@app.delete("/api/gallery/{gallery_id}")
def delete_gallery(gallery_id: int, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery: raise HTTPException(404, "Gallery not found")

    file_path = str(gallery.path)
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{gallery.id}.jpg")
    series_id = gallery.series_id

    db.delete(gallery)
    db.commit()

    series_deleted = False
    if series_id: # type: ignore
        count = db.query(database.Gallery).filter(database.Gallery.series_id == series_id).count()
        if count == 0:
            series = db.query(database.Series).filter(database.Series.id == series_id).first()
            if series:
                db.delete(series)
                db.commit()
                series_deleted = True

    try:
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(thumb_path): os.remove(thumb_path)
        cleanup_parent_folders(file_path)
    except Exception as e: logger.error(f"Error removing files: {e}")

    return {"status": "deleted", "series_deleted": series_deleted}

# --- PLUGINS ---
@app.get("/api/plugins")
def get_plugins(db: Session = Depends(get_db)):
    loaded = manager.load_plugins()
    results = []
    for p_id, p_class in loaded.items():
        plugin = p_class()
        saved = db.query(database.PluginConfig).filter(database.PluginConfig.plugin_id == p_id).all()
        config_map = {c.key: c.value for c in saved}
        fields = []
        for f in plugin.config_fields:
            fields.append({"key": f["key"], "label": f["label"], "value": config_map.get(f["key"], "")})
        results.append({"id": plugin.id, "name": plugin.name, "version": getattr(plugin, 'version', 1.0), "fields": fields})
    return results

@app.post("/api/plugins/config")
def save_plugin_config(payload: dict, db: Session = Depends(get_db)):
    p_id = payload.get("plugin_id")
    cfg = payload.get("config", {})
    for k, v in cfg.items():
        s = db.query(database.PluginConfig).filter(database.PluginConfig.plugin_id == p_id, database.PluginConfig.key == k).first()
        if not s: db.add(database.PluginConfig(plugin_id=p_id, key=k, value=str(v)))
        else: s.value = str(v) # type: ignore
    db.commit()
    return {"status": "saved"}

@app.post("/api/plugins/upload")
async def upload_plugin(file: UploadFile = File(...), force: bool = False):
    clean_name = os.path.basename(file.filename) # type: ignore
    if not clean_name.endswith(".py"): raise HTTPException(400, "Only .py allowed")
    plugin_dir = manager.PLUGIN_DIR
    if not os.path.exists(plugin_dir): os.makedirs(plugin_dir, exist_ok=True)
    temp_path = os.path.join(plugin_dir, f"temp_{clean_name}")
    target_path = os.path.join(plugin_dir, clean_name)
    try:
        with open(temp_path, "wb+") as f: shutil.copyfileobj(file.file, f)
        info = manager.get_plugin_info_from_file(temp_path)
        if not info:
            if os.path.exists(temp_path): os.remove(temp_path)
            raise HTTPException(400, "Invalid plugin")
        new_id, new_ver = info
        existing = manager.get_plugin_instance(new_id) # type: ignore
        if existing:
            old_ver = getattr(existing, 'version', 0.0)
            if new_ver <= old_ver and not force: # type: ignore
                if os.path.exists(temp_path): os.remove(temp_path)
                return {"status": "confirm", "message": f"Version {old_ver} is already installed. Replace with {new_ver}?"}
        if os.path.exists(target_path): os.remove(target_path)
        shutil.move(temp_path, target_path)
        manager.load_plugins()
        return {"status": "success", "id": new_id, "version": new_ver}
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        raise HTTPException(500, str(e))

@app.post("/api/plugins/run")
def run_plugin(payload: dict, db: Session = Depends(get_db)):
    p_id = payload.get("plugin_id")
    url = payload.get("url")
    plugin = manager.get_plugin_instance(p_id) # type: ignore
    if not plugin: raise HTTPException(404, "Plugin not found")
    saved = db.query(database.PluginConfig).filter(database.PluginConfig.plugin_id == p_id).all()
    config_map = {c.key: c.value for c in saved}
    return plugin.scrape(url, config_map)

# --- CATEGORIES / MISC ---
@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    cats = db.query(database.Category).all()
    results = []
    for c in cats:
        book_count = len(c.galleries)
        series_count = db.query(database.Series).filter(database.Series.category_id == c.id).count()
        results.append({"id": c.id, "name": c.name, "count": book_count + series_count})
    return results

@app.post("/api/categories")
def add_category(payload: dict, db: Session = Depends(get_db)):
    name = payload.get("name").strip() # type: ignore
    if not name: raise HTTPException(400, "Empty name")
    if db.query(database.Category).filter(database.Category.name == name).first(): raise HTTPException(400, "Category exists")
    db.add(database.Category(name=name))
    db.commit()
    return {"status": "created"}

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int, force: bool = False, db: Session = Depends(get_db)):
    cat = db.query(database.Category).filter(database.Category.id == cat_id).first()
    if not cat: raise HTTPException(404, "Not found")
    series_in_cat = db.query(database.Series).filter(database.Series.category_id == cat.id).all()
    total_items = len(cat.galleries) + len(series_in_cat)
    if total_items > 0 and not force: return {"status": "conflict", "message": f"Contains {total_items} items"}
    for g in cat.galleries: g.category_id = None
    for s in series_in_cat: s.category_id = None # type: ignore
    db.delete(cat)
    db.commit()
    return {"status": "deleted"}

@app.get("/api/autocomplete")
def autocomplete(db: Session = Depends(get_db)):
    artists = db.query(database.Gallery.artist).distinct().all()
    series = db.query(database.Series.name).distinct().all()
    return {"artists": [a[0] for a in artists if a[0]], "series": [s[0] for s in series if s[0]]}

@app.get("/api/settings")
def get_settings_api(db: Session = Depends(get_db)):
    s_list = db.query(database.Settings).all()
    s_dict = {s.key: s.value for s in s_list}
    if "default_direction" not in s_dict: s_dict["default_direction"] = "LTR" # type: ignore
    if "show_uncategorized" not in s_dict: s_dict["show_uncategorized"] = "false" # type: ignore
    if "server_name" not in s_dict: s_dict["server_name"] = "Manga Server" # type: ignore
    if "auto_backup_enabled" not in s_dict: s_dict["auto_backup_enabled"] = "false" # type: ignore
    if "auto_backup_frequency" not in s_dict: s_dict["auto_backup_frequency"] = "7" # type: ignore
    if "preload_pages" not in s_dict: s_dict["preload_pages"] = "2" # type: ignore
    return s_dict

@app.post("/api/settings")
def save_settings_api(payload: dict, db: Session = Depends(get_db)):
    for k, v in payload.items():
        s = db.query(database.Settings).filter(database.Settings.key == k).first()
        if not s: db.add(database.Settings(key=k, value=str(v)))
        else: s.value = str(v) # type: ignore
    db.commit()
    update_template_globals()
    return {"status": "saved"}

@app.get("/api/logs")
def get_logs_api():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f: 
            lines = f.readlines()
            return {"logs": "".join(lines[-100:])}
    return {"logs": "No logs."}

@app.delete("/api/logs")
def clear_logs_api():
    open(LOG_FILE, "w").close()
    return {"status": "cleared"}

@app.post("/api/upload")
async def upload_gallery_api(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(('.zip', '.cbz')): raise HTTPException(400, "Zip/CBZ only") # type: ignore
    loc = os.path.join(INPUT_DIR, file.filename) # type: ignore
    with open(loc, "wb+") as f: shutil.copyfileobj(file.file, f)
    return {"filename": file.filename, "status": "success"}

@app.get("/api/gallery/{gallery_id}/source")
def get_gallery_source_url(gallery_id: int, db: Session = Depends(get_db)):
    g = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not g: raise HTTPException(404, "Gallery not found")
    return {"source_url": g.source_url if hasattr(g, "source_url") else None}

@app.get("/api/backup")
def backup_db(db: Session = Depends(get_db)):
    data = {"categories": [], "series": [], "tags": [], "galleries": [], "settings": [], "plugin_configs": []}
    
    for c in db.query(database.Category).all(): data["categories"].append({"id":c.id, "name":c.name})
    for s in db.query(database.Series).all(): 
        data["series"].append({
            "id": s.id, 
            "name": s.name, 
            "description": s.description,
            "thumbnail_url": s.thumbnail_url 
        })
    for t in db.query(database.Tag).all(): data["tags"].append({"id":t.id, "name":t.name})
    for st in db.query(database.Settings).all(): data["settings"].append({"key":st.key, "value":st.value})
    
    # Export Plugin Configs
    for pc in db.query(database.PluginConfig).all():
        data["plugin_configs"].append({"plugin_id": pc.plugin_id, "key": pc.key, "value": pc.value})

    for g in db.query(database.Gallery).all():
        data["galleries"].append({
            "id": g.id, "filename": g.filename, "path": g.path, "title": g.title, "artist": g.artist,
            "status": g.status, "pages_read": g.pages_read, "pages_total": g.pages_total,
            "reading_direction": g.reading_direction, "series_id": g.series_id, "category_id": g.category_id,
            "description": g.description, 
            "sort_order": g.sort_order,
            "source_url": g.source_url if hasattr(g, "source_url") else None,
            "tag_names": [t.name for t in g.tags]
        })
    return data

@app.post("/api/restore")
async def restore_db(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    data = json.loads(content)
    
    # Clear Existing
    db.query(database.gallery_tags).delete()
    db.query(database.Gallery).delete()
    db.query(database.Series).delete()
    db.query(database.Category).delete()
    db.query(database.Tag).delete()
    db.query(database.Settings).delete()
    db.query(database.PluginConfig).delete()
    db.commit()
    
    # Restore Basic Tables
    for c in data.get("categories", []): db.add(database.Category(id=c["id"], name=c["name"]))
    for s in data.get("series", []): 
        db.add(database.Series(
            id=s["id"], 
            name=s["name"], 
            description=s.get("description"),
            thumbnail_url=s.get("thumbnail_url")
        ))
    tag_map = {}
    for t in data.get("tags", []): 
        new_tag = database.Tag(id=t["id"], name=t["name"])
        db.add(new_tag)
        tag_map[t["name"]] = new_tag
    for st in data.get("settings", []): db.add(database.Settings(key=st["key"], value=st["value"]))
    
    # Restore Plugins
    for pc in data.get("plugin_configs", []):
        db.add(database.PluginConfig(plugin_id=pc["plugin_id"], key=pc["key"], value=pc["value"]))
        
    db.commit()
    
    # Restore Galleries
    for g in data.get("galleries", []):
        gal = database.Gallery(
            id=g["id"], filename=g["filename"], path=g["path"], title=g["title"], artist=g["artist"],
            status=g["status"], pages_read=g.get("pages_read",0), pages_total=g.get("pages_total",0),
            reading_direction=g.get("reading_direction","LTR"), series_id=g["series_id"], category_id=g["category_id"],
            description=g.get("description"),
            sort_order=g.get("sort_order", 0),
            source_url=g.get("source_url")
        )
        for tn in g.get("tag_names", []):
            if tn in tag_map: gal.tags.append(tag_map[tn])
        db.add(gal)
    db.commit()
    return {"status": "restored"}

@app.post("/api/gallery/{gallery_id}/mark-read")
def mark_gallery_read(gallery_id: int, db: Session = Depends(get_db)):
    g = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not g: raise HTTPException(404, "Gallery not found")
    g.status = "Completed" # type: ignore
    if g.pages_total: g.pages_read = g.pages_total # type: ignore
    db.commit()
    return {"status": "success"}

@app.post("/api/series/{series_id}/mark-read")
def mark_series_read(series_id: int, db: Session = Depends(get_db)):
    s = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not s: raise HTTPException(404, "Series not found")
    for g in s.galleries:
        g.status = "Completed"
        if g.pages_total: g.pages_read = g.pages_total
    db.commit()
    return {"status": "success"}

# --- NEW CLEANUP ENDPOINT ---
@app.post("/api/cleanup")
def cleanup_database_api(db: Session = Depends(get_db)):
    try:
        # 1. Remove "Ghost" Tags (name is empty string)
        empty_tags = db.query(database.Tag).filter(database.Tag.name == "").all()
        count_empty = len(empty_tags)
        for t in empty_tags:
            db.delete(t)
            
        # 2. Remove Unused Tags (no galleries associated)
        unused_tags = db.query(database.Tag).filter(~database.Tag.galleries.any()).all()
        count_unused = len(unused_tags)
        for t in unused_tags:
            db.delete(t)
            
        # 3. Remove Empty Series (no galleries associated)
        empty_series = db.query(database.Series).filter(~database.Series.galleries.any()).all()
        count_series = len(empty_series)
        for s in empty_series:
            db.delete(s)
            
        db.commit()
        
        msg = f"Cleanup complete.\nRemoved {count_empty} ghost tags.\nRemoved {count_unused} unused tags.\nRemoved {count_series} empty series."
        return {"status": "success", "message": msg}
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(500, f"Cleanup failed: {e}")