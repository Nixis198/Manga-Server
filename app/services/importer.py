import os
import shutil
import zipfile
import io
import logging
from sqlalchemy.orm import Session
from PIL import Image

from .. import database
from ..schemas import ImportRequest

# Setup local logger
logger = logging.getLogger(__name__)

def import_gallery(db: Session, staged_id: int, meta: ImportRequest, data_dir: str):
    # 1. Fetch the Staged File record
    staged_file = db.query(database.StagedFile).filter(database.StagedFile.id == staged_id).first()
    if not staged_file:
        raise ValueError("Staged file not found")

    logger.info(f"Starting Import: {meta.title} by {meta.artist}")

    # 2. Define Paths
    # Sanitize inputs
    safe_artist = "".join([c for c in meta.artist if c.isalpha() or c.isdigit() or c in " -_"]).strip()
    
    dest_folder = os.path.join(data_dir, "library", safe_artist)
    os.makedirs(dest_folder, exist_ok=True)
    
    source_path = str(staged_file.path)
    filename = os.path.basename(source_path)
    dest_path = os.path.join(dest_folder, filename)

    # 3. Handle Series (Find existing or Create new)
    series_id = None
    if meta.series:
        existing_series = db.query(database.Series).filter(database.Series.name == meta.series).first()
        if existing_series:
            series_id = existing_series.id
        else:
            new_series = database.Series(name=meta.series)
            db.add(new_series)
            db.flush()
            series_id = new_series.id

    # Handle Category
    category_id = None
    if meta.category:
        existing_cat = db.query(database.Category).filter(database.Category.name == meta.category).first()
        if existing_cat:
            category_id = existing_cat.id
        else:
            new_cat = database.Category(name=meta.category)
            db.add(new_cat)
            db.flush()
            category_id = new_cat.id

    # 4. Create Gallery DB Entry
    new_gallery = database.Gallery(
        filename=filename,
        path=dest_path, 
        title=meta.title,
        artist=meta.artist,
        description=meta.description,
        reading_direction=meta.direction,
        series_id=series_id,
        category_id=category_id,
        status="New",
        pages_total=0 
    )
    
    # 5. Handle Tags
    for tag_name in meta.tags:
        tag = db.query(database.Tag).filter(database.Tag.name == tag_name).first()
        if not tag:
            tag = database.Tag(name=tag_name)
            db.add(tag)
        new_gallery.tags.append(tag)

    db.add(new_gallery)
    db.flush() 

    # 6. Move the File
    try:
        shutil.move(source_path, dest_path)
    except Exception as e:
        db.rollback()
        logger.error(f"Import Failed: Could not move file. {e}")
        raise IOError(f"Failed to move file: {e}")

    # 7. Generate Permanent Thumbnail & Count Pages
    try:
        with zipfile.ZipFile(dest_path, 'r') as z:
            files = sorted([
                f for f in z.namelist() 
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
            ])
            
            if files:
                new_gallery.pages_total = len(files) # type: ignore
                
                # Generate Thumbnail
                img_data = z.read(files[0])
                image = Image.open(io.BytesIO(img_data))
                
                # Resize
                base_height = 400
                w_percent = (base_height / float(image.size[1]))
                w_size = int((float(image.size[0]) * float(w_percent)))
                image = image.resize((w_size, base_height), Image.Resampling.LANCZOS)
                
                thumb_path = os.path.join(data_dir, "thumbnails", f"{new_gallery.id}.jpg")
                image = image.convert('RGB')
                image.save(thumb_path, "JPEG", quality=85)
                
    except Exception as e:
        logger.warning(f"Warning: Could not process zip content: {e}")

    # 8. Cleanup
    db.delete(staged_file)
    db.commit()
    
    logger.info(f"Import Success: Gallery ID {new_gallery.id} created.")
    return new_gallery