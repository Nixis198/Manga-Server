from pydantic import BaseModel
from typing import List, Optional

class ImportRequest(BaseModel):
    title: str
    artist: str
    description: Optional[str] = None
    direction: str = "RTL"  # Default to Manga (Right-to-Left)
    series: Optional[str] = None
    tags: List[str] = []