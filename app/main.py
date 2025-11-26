# app/main.py
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import os
from . import database

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
    print(f"Server started. Data directory: {DATA_DIR}")

# Mount Static Files (CSS, JS, Thumbnails)
# We will create the 'static' folder in the next steps
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")

@app.get("/")
def read_root():
    return {"status": "Manga Server is running", "next_step": "Build the frontend"}

# Placeholder for the Scanner API
@app.get("/api/scan")
def scan_input_folder(db: Session = Depends(get_db)):
    # This is where we will write the logic to look through INPUT_DIR
    # and populate the StagedFile table.
    return {"message": "Scanner not implemented yet"}