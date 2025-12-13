from pydantic import BaseModel
from typing import List, Optional

class ImportRequest(BaseModel):
    title: str
    artist: str
    description: Optional[str] = None
    direction: str = "LTR"
    series: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []