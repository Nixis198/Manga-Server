import os
import shutil
import logging
import zipfile
import io
import time
import json
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

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

# Ensure Log Directory Exists immediately
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

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

def get_series_cover(series):
    """ Determines the correct thumbnail URL based on settings. """
    if not series.galleries:
        return ""
        
    sorted_gals = sorted(series.galleries, key=lambda x: (x.sort_order, x.id))
    
    if series.thumbnail_url == "__reading__":
        reading_gal = next((g for g in sorted_gals if g.status == "Reading"), None)
        if reading_gal:
            return f"/thumbnails/{reading_gal.id}.jpg"
        return f"/thumbnails/{sorted_gals[0].id}.jpg"

    if series.thumbnail_url:
        return series.thumbnail_url
        
    return f"/thumbnails/{sorted_gals[0].id}.jpg"

def build_search_string(title, artist, extra_list=None):
    """ Creates a lowercase searchable string from metadata """
    terms = [title, artist]
    if extra_list:
        terms.extend(extra_list)
    return " ".join([str(t).lower() for t in terms if t])

@app.on_event("startup")
async def startup_event():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    database.init_db()

    update_template_globals()
    
    # --- CLEANUP: REMOVE GHOST TAGS ---
    # This runs once on startup to fix your database
    db = database.SessionLocal()
    try:
        bad_tags = db.query(database.Tag).filter(database.Tag.name == "").all()
        if bad_tags:
            logger.info(f"Cleanup: Found {len(bad_tags)} empty tags. Removing them...")
            for t in bad_tags:
                # Clear relationships first to be safe
                t.galleries = []
                t.series = []
                db.delete(t)
            db.commit()
            logger.info("Cleanup: Empty tags removed.")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
    finally:
        db.close()
        
    logger.info("Server Started Successfully")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")
templates = Jinja2Templates(directory="app/templates")

def update_template_globals():
    """Refreshes the server_name global variable for all templates."""
    db = database.SessionLocal()
    try:
        setting = db.query(database.Settings).filter(database.Settings.key == "server_name").first()
        name = setting.value if setting else "Manga Server"
        templates.env.globals["server_name"] = name
    finally:
        db.close()

# --- API ENDPOINTS: PAGES ---

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    items = []
    
    # 1. Standalone Galleries
    standalone = db.query(database.Gallery).filter(database.Gallery.series_id == None).all()
    for g in standalone:
        items.append({
            "type": "gallery",
            "id": g.id,
            "title": g.title,
            "artist": g.artist,
            "status": g.status,
            "pages_read": g.pages_read,
            "pages_total": g.pages_total,
            "category": g.category.name if g.category else "",
            "thumb": f"/thumbnails/{g.id}.jpg",
            "series": "", 
            "tags": [t.name for t in g.tags],
            "description": g.description if g.description else "", # type: ignore
            "search_data": build_search_string(g.title, g.artist)
        })

    # 2. Series
    all_series = db.query(database.Series).all()
    for s in all_series:
        if not s.galleries:
            continue
            
        thumb = get_series_cover(s)
        total_count = len(s.galleries)
        read_count = sum(1 for g in s.galleries if g.status == "Completed")
        
        any_progress = any(g.status != "New" for g in s.galleries)
        
        series_tags = [t.name for t in s.tags]
        child_tags = []
        for g in s.galleries:
            for t in g.tags:
                child_tags.append(t.name)
        all_search_tags = list(set(series_tags + child_tags))
        
        if series_tags:
            display_tags = series_tags
        else:
            display_tags = sorted(list(set(child_tags)))

        child_titles = [g.title for g in s.galleries]
        child_artists = [g.artist for g in s.galleries]
        search_blob = build_search_string(s.name, s.artist, child_titles + child_artists + all_search_tags)

        items.append({
            "type": "series",
            "id": s.id,
            "title": s.name,
            "artist": s.artist if s.artist else "Various",  # type: ignore
            "status": f"{len(s.galleries)} Items", 
            "category": s.category.name if s.category else "Series",
            "thumb": thumb,
            "count": total_count,
            "read_count": read_count,
            "is_new": not any_progress,
            "series": s.name,
            "tags": display_tags,
            "description": s.description if s.description else "", # type: ignore
            "search_data": search_blob
        })

    items.sort(key=lambda x: x['title'].lower())
        
    return templates.TemplateResponse("library.html", {
        "request": request, 
        "galleries": items
    })

@app.get("/series/{series_id}", response_class=HTMLResponse)
def view_series_page(series_id: int, request: Request, db: Session = Depends(get_db)):
    series = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
        
    galleries = sorted(series.galleries, key=lambda x: (x.sort_order, x.id))
    cover_url = get_series_cover(series)

    if series.tags:
        display_tags = [t.name for t in series.tags]
    else:
        child_tags = []
        for g in series.galleries:
            for t in g.tags:
                child_tags.append(t.name)
        display_tags = sorted(list(set(child_tags)))
    
    return templates.TemplateResponse("series.html", {
        "request": request, 
        "series": series, 
        "galleries": galleries,
        "cover_url": cover_url,
        "display_tags": display_tags
    })

@app.get("/reader/{gallery_id}", response_class=HTMLResponse)
def open_reader(gallery_id: int, request: Request, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    
    if gallery.status == "New": # type: ignore
        gallery.status = "Reading" # type: ignore
        db.commit()
    
    return templates.TemplateResponse("reader.html", {"request": request, "gallery": gallery})

@app.get("/staging", response_class=HTMLResponse)
def read_staging(request: Request):
    return templates.TemplateResponse("staging.html", {"request": request})

@app.get("/settings", response_class=HTMLResponse)
def read_settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

# --- API ENDPOINTS: ACTIONS ---

@app.post("/api/scan")
def scan_input_folder():
    return scanner.scan_input_directory(INPUT_DIR)

@app.get("/api/staged")
def get_staged_files(db: Session = Depends(get_db)):
    return db.query(database.StagedFile).all()

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
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/read/{gallery_id}/{page}")
def read_page_image(gallery_id: int, page: int, db: Session = Depends(get_db)):
    image_data = reader.get_page_image(db, gallery_id, page)
    return Response(content=image_data, media_type="image/jpeg")

@app.post("/api/progress/{gallery_id}/{page}")
def update_progress(gallery_id: int, page: int, db: Session = Depends(get_db)):
    g = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not g: raise HTTPException(404, "Not found")
    
    g.pages_read = page # type: ignore
    
    # Progress Logic
    if g.pages_total and page >= g.pages_total: # type: ignore
        g.status = "Completed" # type: ignore
    elif page > 1:
        g.status = "Reading" # type: ignore
    else:
        g.status = "New" # type: ignore
        
    db.commit()
    return {"status": "updated"}

# --- METADATA UPDATES (Gallery & Series) ---

@app.post("/api/gallery/{gallery_id}/update")
def update_gallery_metadata(gallery_id: int, request: schemas.ImportRequest, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery: raise HTTPException(404, "Gallery not found")
    
    gallery.title = request.title # type: ignore
    gallery.artist = request.artist # type: ignore
    gallery.description = request.description # type: ignore
    if request.direction: gallery.reading_direction = request.direction # type: ignore
    
    if request.series:
        s = db.query(database.Series).filter(database.Series.name == request.series).first()
        if not s:
            s = database.Series(name=request.series)
            db.add(s)
            db.flush()
        gallery.series_id = s.id
    else:
        gallery.series_id = None # type: ignore

    if request.category:
        c = db.query(database.Category).filter(database.Category.name == request.category).first()
        if not c:
            c = database.Category(name=request.category)
            db.add(c)
            db.flush()
        gallery.category_id = c.id
    else:
        gallery.category_id = None # type: ignore

    # Handle Tags
    gallery.tags.clear()
    for t_name in request.tags:
        t_name = t_name.strip()
        if not t_name: continue # <--- FIX: Prevent empty tags
        
        t = db.query(database.Tag).filter(database.Tag.name == t_name).first()
        if not t:
            t = database.Tag(name=t_name)
            db.add(t)
        gallery.tags.append(t)
        
    db.commit()
    return {"status": "success"}

@app.post("/api/series/{series_id}/update")
def update_series_metadata(series_id: int, payload: dict, db: Session = Depends(get_db)):
    s = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not s: raise HTTPException(404, "Series not found")
    
    if "name" in payload: s.name = payload["name"]
    if "thumbnail_url" in payload: s.thumbnail_url = payload["thumbnail_url"]
    if "artist" in payload: s.artist = payload["artist"]
    if "description" in payload: s.description = payload["description"]
    
    if "category" in payload:
        c_name = payload["category"]
        if c_name:
            c = db.query(database.Category).filter(database.Category.name == c_name).first()
            if not c:
                c = database.Category(name=c_name)
                db.add(c)
            s.category = c
        else:
            s.category = None

    if "tags" in payload:
        s.tags.clear()
        for t_name in payload["tags"]:
            t_name = t_name.strip()
            if not t_name: continue # <--- FIX: Prevent empty tags
            
            t = db.query(database.Tag).filter(database.Tag.name == t_name).first()
            if not t:
                t = database.Tag(name=t_name)
                db.add(t)
            s.tags.append(t)

    if "order" in payload:
        for idx, g_id in enumerate(payload["order"]):
            g = db.query(database.Gallery).filter(database.Gallery.id == g_id).first()
            if g and g.series_id == s.id: # type: ignore
                g.sort_order = idx + 1  # type: ignore
                
    db.commit()
    return {"status": "success"}

# --- DOWNLOADS ---

@app.get("/api/download/{gallery_id}")
def download_gallery(gallery_id: int, db: Session = Depends(get_db)):
    gallery = db.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery or not os.path.exists(gallery.path): # type: ignore
        raise HTTPException(404, "File not found")
    return FileResponse(path=gallery.path, filename=os.path.basename(gallery.path), media_type='application/octet-stream') # type: ignore

@app.get("/api/download/series/{series_id}")
def download_series(series_id: int, db: Session = Depends(get_db)):
    series = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not series: raise HTTPException(404, "Series not found")
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        for gallery in series.galleries:
            if os.path.exists(gallery.path):
                zf.write(gallery.path, arcname=gallery.filename)
                
    zip_buffer.seek(0)
    return StreamingResponse(
        iter([zip_buffer.getvalue()]), 
        media_type="application/zip", 
        headers={"Content-Disposition": f"attachment; filename={series.name}.zip"}
    )

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
            
        results.append({
            "id": plugin.id, 
            "name": plugin.name, 
            "version": getattr(plugin, 'version', 1.0), 
            "fields": fields
        })
    return results

@app.post("/api/plugins/config")
def save_plugin_config(payload: dict, db: Session = Depends(get_db)):
    p_id = payload.get("plugin_id")
    cfg = payload.get("config", {})
    for k, v in cfg.items():
        s = db.query(database.PluginConfig).filter(database.PluginConfig.plugin_id == p_id, database.PluginConfig.key == k).first()
        if not s:
            db.add(database.PluginConfig(plugin_id=p_id, key=k, value=str(v)))
        else:
            s.value = str(v) # type: ignore
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

# --- OTHER HELPERS ---

@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    cats = db.query(database.Category).all()
    return [{"id": c.id, "name": c.name, "count": len(c.galleries)} for c in cats]

@app.post("/api/categories")
def add_category(payload: dict, db: Session = Depends(get_db)):
    name = payload.get("name").strip() # type: ignore
    if not name: raise HTTPException(400, "Empty name")
    if db.query(database.Category).filter(database.Category.name == name).first():
        raise HTTPException(400, "Category exists")
    db.add(database.Category(name=name))
    db.commit()
    return {"status": "created"}

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int, force: bool = False, db: Session = Depends(get_db)):
    cat = db.query(database.Category).filter(database.Category.id == cat_id).first()
    if not cat: raise HTTPException(404, "Not found")
    if len(cat.galleries) > 0 and not force:
        return {"status": "conflict", "message": f"Contains {len(cat.galleries)} items"}
    for g in cat.galleries: g.category_id = None
    db.delete(cat)
    db.commit()
    return {"status": "deleted"}

@app.get("/api/autocomplete")
def autocomplete(db: Session = Depends(get_db)):
    artists = db.query(database.Gallery.artist).distinct().all()
    series = db.query(database.Series.name).distinct().all()
    return {
        "artists": [a[0] for a in artists if a[0]],
        "series": [s[0] for s in series if s[0]]
    }

@app.get("/api/settings")
def get_settings_api(db: Session = Depends(get_db)):
    s_list = db.query(database.Settings).all()
    s_dict = {s.key: s.value for s in s_list}
    if "default_direction" not in s_dict: s_dict["default_direction"] = "LTR" # type: ignore
    if "show_uncategorized" not in s_dict: s_dict["show_uncategorized"] = "false" # type: ignore
    if "server_name" not in s_dict: s_dict["server_name"] = "Manga Server" # type: ignore
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

@app.get("/api/backup")
def backup_db(db: Session = Depends(get_db)):
    data = {"categories": [], "series": [], "tags": [], "galleries": [], "settings": []}
    for c in db.query(database.Category).all(): data["categories"].append({"id":c.id, "name":c.name})
    for s in db.query(database.Series).all(): data["series"].append({"id":s.id, "name":s.name, "description":s.description})
    for t in db.query(database.Tag).all(): data["tags"].append({"id":t.id, "name":t.name})
    for st in db.query(database.Settings).all(): data["settings"].append({"key":st.key, "value":st.value})
    for g in db.query(database.Gallery).all():
        data["galleries"].append({
            "id": g.id, "filename": g.filename, "path": g.path, "title": g.title, "artist": g.artist,
            "status": g.status, "pages_read": g.pages_read, "pages_total": g.pages_total,
            "reading_direction": g.reading_direction, "series_id": g.series_id, "category_id": g.category_id,
            "description": g.description, "tag_names": [t.name for t in g.tags]
        })
    return data

@app.post("/api/restore")
async def restore_db(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    data = json.loads(content)
    
    db.query(database.gallery_tags).delete()
    db.query(database.Gallery).delete()
    db.query(database.Series).delete()
    db.query(database.Category).delete()
    db.query(database.Tag).delete()
    db.query(database.Settings).delete()
    db.commit()
    
    for c in data.get("categories", []): db.add(database.Category(id=c["id"], name=c["name"]))
    for s in data.get("series", []): db.add(database.Series(id=s["id"], name=s["name"], description=s.get("description")))
    tag_map = {}
    for t in data.get("tags", []): 
        new_tag = database.Tag(id=t["id"], name=t["name"])
        db.add(new_tag)
        tag_map[t["name"]] = new_tag
    for st in data.get("settings", []): db.add(database.Settings(key=st["key"], value=st["value"]))
    db.commit()
    
    for g in data.get("galleries", []):
        gal = database.Gallery(
            id=g["id"], filename=g["filename"], path=g["path"], title=g["title"], artist=g["artist"],
            status=g["status"], pages_read=g.get("pages_read",0), pages_total=g.get("pages_total",0),
            reading_direction=g.get("reading_direction","LTR"), series_id=g["series_id"], category_id=g["category_id"],
            description=g.get("description")
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
    
    # Set to completed state
    g.status = "Completed" # type: ignore
    if g.pages_total: # type: ignore
        g.pages_read = g.pages_total
        
    db.commit()
    return {"status": "success"}

@app.post("/api/series/{series_id}/mark-read")
def mark_series_read(series_id: int, db: Session = Depends(get_db)):
    s = db.query(database.Series).filter(database.Series.id == series_id).first()
    if not s: raise HTTPException(404, "Series not found")
    
    # Update ALL galleries in series
    for g in s.galleries:
        g.status = "Completed"
        if g.pages_total:
            g.pages_read = g.pages_total
            
    db.commit()
    return {"status": "success"}