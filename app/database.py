# app/database.py
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Table, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os

# Ensure data directory exists
DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR}/manga.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Association Table for Tags ---
gallery_tags = Table('gallery_tags', Base.metadata,
    Column('gallery_id', Integer, ForeignKey('galleries.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

# --- Models ---

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    galleries = relationship("Gallery", back_populates="category")

class Settings(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(String)

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

class Series(Base):
    __tablename__ = "series"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(Text, nullable=True)
    
    # Relationship to get all galleries in this series
    galleries = relationship("Gallery", back_populates="series")

class Gallery(Base):
    __tablename__ = "galleries"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # File Info
    filename = Column(String, index=True)
    path = Column(String)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    circle = Column(String, nullable=True)
    parody = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String, default="New")
    pages_read = Column(Integer, default=0) # type: ignore
    pages_total = Column(Integer, default=0) # type: ignore
    reading_direction = Column(String, default="LTR")
    
    # Relationships
    series_id = Column(Integer, ForeignKey('series.id'), nullable=True)
    series = relationship("Series", back_populates="galleries")
    
    # Category Relationship
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    category = relationship("Category", back_populates="galleries")
    
    tags = relationship("Tag", secondary=gallery_tags, backref="galleries")

class StagedFile(Base):
    """
    Files found in the 'Input' folder that haven't been imported yet.
    This acts as a temporary holding area for the UI.
    """
    __tablename__ = "staged_files"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True)
    path = Column(String) # Full path in /data/input
    
    # Pre-filled metadata (if auto-detected or plugin run)
    suggested_title = Column(String, nullable=True)
    suggested_artist = Column(String, nullable=True)

# Create tables
def init_db():
    Base.metadata.create_all(bind=engine)