# Cloud Run Image Rec API

A high-performance, Flask-based image recognition and archiving system designed for Google Cloud Run. It uses a **Two-Stage Hybrid Analysis Engine** to compare uploaded images against a cloud-based library (Google Cloud Storage) with near-instant speed.

## Key Features

- **Cloud-Native**: Images are stored in a GCS Bucket (`image_rec_resource`), not the local filesystem.
- **In-Memory Indexing**: At startup, the system downloads the database and builds an O(1) in-memory index of **Perceptual Hashes** and **Color Histograms**.
- **Two-Stage Analysis**:
    1.  **Fast Filter (O(N) -> O(1))**: Scans the entire in-memory index (thousands of images) in milliseconds to find top candidates using Hash Difference and Histogram Correlation. **Zero network calls**.
    2.  **Deep Verification**: Downloads *only* the top candidates (max 25) to perform heavy-duty checks: AKAZE Feature Matching, Deep Template Scanning, and OCR.
- **Real-Time Feedback**: UI shows live loading progress and analysis status.

## How It Works

### 1. Database Loading (The "Index" Phase)
Before analysis can begin, the "Brain" must be loaded.
1.  User clicks **Load Database**.
2.  Server lists all images in the GCS bucket (`阿丹哥/` and `開源/`).
3.  Server downloads each image once.
4.  **Computation**: Calculates the `phash` (structure signature) and `histogram` (color signature).
5.  **Storage**: Saves `{url, hash, hist}` into a global Python dictionary (RAM).
6.  *Result*: The server now "knows" what every image looks like without needing to touch GCS again for searching.

### 2. Analysis Engine (The "Search" Phase)
When an image is uploaded to `/analyze`:
1.  **Query Signature**: Server computes the `hash` and `hist` of the uploaded file.
2.  **Memory Scan (Fast)**:
    - It iterates through the global dictionary.
    - Compares `Hash Diff` (Integer subtraction).
    - Compares `Color Correlation` (Matrix multiplication).
    - **Filter**: Keeps candidates where `Hash Diff <= 35` OR `Color Score > 0.55`.
3.  **Candidate Selection**: Sorts by best match and picks the top 25.
4.  **Deep Scan (Accurate)**:
    - *Only now* does it download the actual image bytes for the top 25 candidates.
    - Runs **AKAZE** (keypoint matching) to find rotated/cropped matches.
    - Runs **Deep Scan** (multi-scale template matching) to find small partial matches.
    - Runs **OCR** to match text content.
5.  **Scoring**: Returns the highest match score (e.g., "AKAZE 95%", "SCAN 70%").

## Project Structure

- `main.py`: Flask server. Handles API endpoints (`/status`, `/load_db`, `/analyze`) and manages the global `DATABASE` state.
- `logic.py`: The brain. Contains:
    - `load_database()`: Index builder.
    - `check_image_engine()`: The two-stage search logic.
    - `compute_image_signature()`: Hash/Hist generator.
    - Computer Vision algorithms (OpenCV, Tesseract).
- `templates/index.html`: Modern UI with Drag & Drop, Live Progress, and Status monitoring.
- `Dockerfile`: Deployment config for Cloud Run (Python 3.9 + Tesseract).

## Usage

### Local Run
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run Server
python main.py
```
Visit `http://localhost:8080`.

### Database Management
- **Load**: Click "Load Database" on the dashboard.
- **Add**: Use the `/archive` endpoint to upload new reference images to GCS. They are automatically added to the live RAM index.
