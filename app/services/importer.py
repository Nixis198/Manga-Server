import os
import shutil
import zipfile
from sqlalchemy.orm import Session
from PIL import Image
import io

from .. import database
from ..schemas import ImportRequest

def import_gallery(db: Session, staged_id: int, meta: ImportRequest, data_dir: str):
    # 1. Fetch the Staged File record
    staged_file = db.query(database.StagedFile).filter(database.StagedFile.id == staged_id).first()
    if not staged_file:
        raise ValueError("Staged file not found")

    # 2. Define Paths
    # Sanitize inputs to prevent folder errors (e.g. removing "/" from artist names)
    safe_artist = "".join([c for c in meta.artist if c.isalpha() or c.isdigit() or c in " -_"]).strip()
    safe_title = "".join([c for c in meta.title if c.isalpha() or c.isdigit() or c in " -_"]).strip()
    
    # Structure: /data/library/Artist/Title/Filename.zip
    dest_folder = os.path.join(data_dir, "library", safe_artist, safe_title)
    os.makedirs(dest_folder, exist_ok=True)
    
    dest_path = os.path.join(dest_folder, os.path.basename(staged_file.path))

    # 3. Handle Series (Find existing or Create new)
    series_id = None
    if meta.series:
        # Check if series exists
        existing_series = db.query(database.Series).filter(database.Series.name == meta.series).first()
        if existing_series:
            series_id = existing_series.id
        else:
            # Create new series
            new_series = database.Series(name=meta.series)
            db.add(new_series)
            db.flush() # Flush to get the ID
            series_id = new_series.id

    # 4. Create Gallery DB Entry
    new_gallery = database.Gallery(
        filename=os.path.basename(staged_file.path),
        path=dest_path, # We store the full internal path
        title=meta.title,
        artist=meta.artist,
        description=meta.description,
        reading_direction=meta.direction,
        series_id=series_id,
        status="New"
    )
    
    # 5. Handle Tags
    for tag_name in meta.tags:
        tag = db.query(database.Tag).filter(database.Tag.name == tag_name).first()
        if not tag:
            tag = database.Tag(name=tag_name)
            db.add(tag)
        new_gallery.tags.append(tag)

    db.add(new_gallery)
    db.flush() # We need new_gallery.id for the thumbnail filename

    # 6. Move the File
    try:
        shutil.move(staged_file.path, dest_path)
    except Exception as e:
        db.rollback()
        raise IOError(f"Failed to move file: {e}")

    # 7. Generate Permanent Thumbnail
    # We extract the first image, resize it (height 400px), and save as JPG
    try:
        with zipfile.ZipFile(dest_path, 'r') as z:
            files = sorted([f for f in z.namelist() if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))])
            if files:
                img_data = z.read(files[0])
                image = Image.open(io.BytesIO(img_data))
                
                # Resize for optimization (preserve aspect ratio)
                base_height = 400
                w_percent = (base_height / float(image.size[1]))
                w_size = int((float(image.size[0]) * float(w_percent)))
                image = image.resize((w_size, base_height), Image.Resampling.LANCZOS)
                
                # Save to /data/thumbnails/{id}.jpg
                thumb_path = os.path.join(data_dir, "thumbnails", f"{new_gallery.id}.jpg")
                image = image.convert('RGB') # Ensure it saves as JPG even if original was PNG
                image.save(thumb_path, "JPEG", quality=85)
    except Exception as e:
        print(f"Warning: Could not generate thumbnail: {e}")

    # 8. Cleanup
    db.delete(staged_file)
    db.commit()
    
    return new_gallery