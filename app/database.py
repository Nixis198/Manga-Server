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

# --- Association Tables ---

# Links Galleries <-> Tags
gallery_tags = Table('gallery_tags', Base.metadata,
    Column('gallery_id', Integer, ForeignKey('galleries.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

# Links Series <-> Tags (NEW)
series_tags = Table('series_tags', Base.metadata,
    Column('series_id', Integer, ForeignKey('series.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

# --- Models ---

class PluginConfig(Base):
    __tablename__ = "plugin_configs"
    plugin_id = Column(String, primary_key=True, index=True)
    key = Column(String, primary_key=True, index=True) 
    value = Column(String)

class Settings(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(String)

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    # Relationships
    galleries = relationship("Gallery", back_populates="category")
    series = relationship("Series", back_populates="category") # NEW

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    # Relationships
    galleries = relationship("Gallery", secondary=gallery_tags, back_populates="tags")
    series = relationship("Series", secondary=series_tags, back_populates="tags") # NEW

class Series(Base):
    __tablename__ = "series"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    thumbnail_url = Column(String, nullable=True)
    
    # NEW METADATA FIELDS
    artist = Column(String, default="")
    description = Column(Text, default="")
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    
    # Relationships
    galleries = relationship("Gallery", back_populates="series")
    category = relationship("Category", back_populates="series") # NEW
    tags = relationship("Tag", secondary=series_tags, back_populates="series") # NEW

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
    pages_read = Column(Integer, default=0)
    pages_total = Column(Integer, default=0)
    reading_direction = Column(String, default="LTR")
    sort_order = Column(Integer, default=0)

    # Relationships
    series_id = Column(Integer, ForeignKey('series.id'), nullable=True)
    series = relationship("Series", back_populates="series") # This should be "series", not "galleries"
    # Actually, fixing a potential typo in your old file:
    series = relationship("Series", back_populates="galleries")
    
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    category = relationship("Category", back_populates="galleries")
    
    tags = relationship("Tag", secondary=gallery_tags, back_populates="galleries")

class StagedFile(Base):
    __tablename__ = "staged_files"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True)
    path = Column(String) 
    suggested_title = Column(String, nullable=True)
    suggested_artist = Column(String, nullable=True)

# Create tables
def init_db():
    Base.metadata.create_all(bind=engine)