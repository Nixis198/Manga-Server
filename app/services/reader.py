import zipfile
import os
from fastapi import HTTPException
from .. import database

def get_page_image(db_session, gallery_id: int, page_num: int):
    # 1. Get the gallery path from DB
    gallery = db_session.query(database.Gallery).filter(database.Gallery.id == gallery_id).first()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    # 2. Open Zip and find file list
    if not os.path.exists(gallery.path):
        raise HTTPException(status_code=404, detail="Gallery file missing on disk")

    try:
        with zipfile.ZipFile(gallery.path, 'r') as z:
            # Filter for images and sort them naturally
            images = sorted([
                f for f in z.namelist() 
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
            ])
            
            # Check if page is in range (page_num is 1-based index)
            if page_num < 1 or page_num > len(images):
                raise HTTPException(status_code=404, detail="Page not found")
                
            # 3. Read the specific image
            image_filename = images[page_num - 1]
            return z.read(image_filename)
            
    except Exception as e:
        print(f"Error reading zip: {e}")
        raise HTTPException(status_code=500, detail="Error reading gallery archive")