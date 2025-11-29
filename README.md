# Self-Hosted Manga & Comic Server

A robust, self-hosted media server designed specifically for managing and reading digital comics and manga. Built with **Python (FastAPI)** and **Docker**, it features a "Staging" workflow to ensure metadata is clean before files enter your permanent library.

## 🚀 Features

### 📚 Library Management
* **Staging Workflow:** New files aren't dumped into your library immediately. They go to a "Staging Area" where you verify metadata, fix titles, and assign artists before import.
* **Series Support:** Group multiple galleries into a Series.
    * **Drag & Drop Sorting:** Reorder volumes/chapters visually.
    * **Custom Thumbnails:** Pick any gallery cover to represent the whole series.
    * **Auto-Grouping:** The library view automatically stacks galleries into folders.
* **Smart Organization:** Files are physically moved and renamed on disk (`/Library/Artist/Series/File.zip`) to keep your filesystem clean.
* **Categories:** Organize content into custom categories (e.g., Manga, Comics, Doujinshi) with instant filtering.

### 📖 The Reader
* **Web-Based:** Read directly in your browser (Mobile/Desktop friendly).
* **Reading Modes:** Supports Right-to-Left (Manga) and Left-to-Right (Comic).
* **Progress Tracking:** Remembers exactly which page you left off on.
* **Jump-to-Page:** Click the page number to type and jump instantly.
* **Fit Modes:** Fit Height, Fit Width, or Original Size.

### 🛠️ System Tools
* **Web Upload:** Drag & Drop ZIP/CBZ files directly to the server via the browser.
* **Database Backup/Restore:** Export your entire library metadata to JSON and restore it with one click.
* **Live Logs:** View and clear server logs directly from the Settings page.
* **Context Menus:** Right-click galleries in the library to Quick Read or Edit Metadata.

## 📦 Installation

### Prerequisites
* [Docker Desktop](https://www.docker.com/products/docker-desktop)

### 1. Start the Server
Run the following command in the root directory:
```bash
docker-compose up -d
```

### 2\. Access the Interface

Open your browser and navigate to:
`http://localhost:8000`

## 📖 How to Use

### 1\. Add Comics (Two Methods)

  * **Web Upload:** Go to the **Upload** tab and drag `.zip` or `.cbz` files into the drop zone.
  * **Local Move:** Move files manually into the `data/input/` folder on your computer.

### 2\. Import & Tag

1.  Go to the **Import** tab.
2.  Click a file on the left.
3.  Fill in the **Title**, **Artist**, and optional **Series**.
4.  Click **Save & Import**.
      * *The file is moved to `data/library/[Artist]/[Series]/[Title].zip`*

### 3\. Organize Series

1.  In the **Library**, click on a Series folder.
2.  Click **Series Settings** to rename or change the cover image.
3.  Click **Manage Sort Order** to drag-and-drop chapters into the correct reading order.

### 4\. Backup Data

1.  Go to **Settings**.
2.  Under "Database Maintenance", click **Download Backup**.
3.  To restore, click **Restore Backup** and select your JSON file.

## 🔧 Directory Structure

```text
/manga-server
├── app/                 # Source Code
│   ├── main.py          # API & Routing
│   ├── database.py      # Database Models
│   ├── services/        # Logic (Scanner, Importer)
│   └── templates/       # HTML Frontend
└── data/                # Persistent Data (Mounted Volume)
    ├── input/           # Staging Area (Uploads go here)
    ├── library/         # Organized Collection
    ├── thumbnails/      # Generated Cover Images
    ├── logs/            # Server Logs
    └── manga.db         # SQLite Database
```

## 📝 Development Notes

To reset the system (Wipe DB and move files back to Input) for testing:

```bash
python reset_data.py
```
