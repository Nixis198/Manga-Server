# Self-Hosted Manga & Comic Server

A lightweight, self-hosted media server designed specifically for managing and reading digital comics and manga. Built with **Python (FastAPI)** and **Docker**, it features a unique "Staging" workflow to ensure your library metadata is perfect before files are imported.

## 🚀 Features

* **Self-Hosted:** You own your data. Runs locally on any OS via Docker.
* **Staging Workflow:** New files aren't dumped into your library immediately. They go to a "Staging Area" where you can verify metadata, fix titles, and assign artists before import.
* **Smart Metadata:** Supports manual editing and future plugin support (e.g., Fakku URL parsing) to auto-fill metadata.
* **Reader Experience:**
    * Web-based reader (no app required).
    * Supports Right-to-Left (Manga) and Left-to-Right (Comic) reading modes.
    * "Fit to Width/Height" and Pre-loading settings.
* **Organization:** Group galleries into Series. Filter by Artist or Tags.
* **Format Support:** Native support for `.zip` (and `.cbz`) archives.

## 🛠️ Architecture

The project is containerized using Docker to ensure consistency across different operating systems.

* **Backend:** Python 3.10 + FastAPI
* **Database:** SQLite (Stored in `/data/db.sqlite`)
* **Frontend:** HTML/JS with Jinja2 Templates (Served by FastAPI)

### Directory Structure
```text
/manga-server
├── app/                 # Application Source Code
│   ├── main.py          # Server Entry Point
│   ├── database.py      # Database Models & Setup
│   ├── services/        # Background Logic (Scanner, Importer)
│   └── templates/       # Frontend HTML
└── data/                # Mounted Volume (Persists Data)
    ├── input/           # Dump new ZIPs here (Staging Area)
    ├── library/         # Organized Library (Artist/Series/Title)
    ├── thumbnails/      # Generated Covers
    └── manga.db         # SQLite Database
````

## 📦 Installation & Usage

### Prerequisites

  * [Docker Desktop](https://www.docker.com/products/docker-desktop) installed on your machine.

### 1\. Clone the Repository

```bash
git clone https://github.com/Nixis198/manga-server.git
cd manga-server
```

### 2\. Run with Docker

```bash
docker-compose up -d
```

### 3\. Access the Web Interface

Open your browser and navigate to:
`http://localhost:8000`

## 📖 How to Add Comics

1.  **Drop Files:** Place your `.zip` or `.cbz` files into the `data/input/` folder.
2.  **Scan:** The server detects new files and adds them to the "Staging" tab in the web UI.
3.  **Edit:** Click on a staged file in the browser to add Title, Artist, and Tags.
4.  **Import:** Click "Save & Import". The server will:
      * Move the file to `data/library/[Artist]/[Title]/`
      * Generate a thumbnail.
      * Add it to your main library view.

## 🔧 Development

If you want to contribute or modify the code:

1.  **Install Python Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run Locally (without Docker):**
    ```bash
    uvicorn app.main:app --reload
    ```

## 📝 Planned Features

  - [ ] Metadata Plugins (Auto-scrape info from URLs)
  - [ ] CBR/RAR support
  - [ ] User Accounts & Reading History per user
