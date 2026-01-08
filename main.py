from flask import Flask, request, jsonify, render_template
from flask.json.provider import DefaultJSONProvider
import logic
import os
import threading
import numpy as np
import json

app = Flask(__name__)

# --- Fix JSON Serialization for Numpy ---
class NumpyJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, np.float32):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

app.json = NumpyJSONProvider(app)

# --- Global State ---
DATABASE = {}
DB_LOADING = False
DB_LOADED = False
DB_COUNT = 0

def background_load_db():
    global DATABASE, DB_LOADING, DB_LOADED, DB_COUNT
    print("Starting background DB load...")
    
    def progress_update(current_count):
        global DB_COUNT
        DB_COUNT = current_count
        
    DATABASE, count = logic.load_database(progress_callback=progress_update)
    DB_COUNT = count
    DB_LOADING = False
    DB_LOADED = True
    print(f"Database Loaded: {DB_COUNT} images")

DEFAULT_CFG = {
    'use_hash': True, 'hash_cut': 15, 
    'use_color': True, 'color_th': 0.90, 
    'use_scan': True, 'scan_th': 0.60, 
    'use_ocr': True
}

@app.route("/", methods=["GET"])
def index():
    return render_template('index.html', count=DB_COUNT if DB_LOADED else 0)

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "loaded": DB_LOADED,
        "loading": DB_LOADING,
        "count": DB_COUNT
    })

@app.route("/load_db", methods=["POST"])
def trigger_load():
    global DB_LOADING, DB_LOADED
    if DB_LOADING:
        return jsonify({"status": "already_loading"})
    if DB_LOADED:
        # Optional: Allow reload? For now, just say loaded.
        return jsonify({"status": "loaded", "count": DB_COUNT})
    
    DB_LOADING = True
    thread = threading.Thread(target=background_load_db)
    thread.daemon = True
    thread.start()
    return jsonify({"status": "started"})

@app.route("/analyze", methods=["POST"])
def analyze():
    if not DB_LOADED:
        return jsonify({"error": "Database not loaded. Please load database first."}), 503

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "No selected file"}), 400

    # Reload ignore pairs just in case
    ignores = logic.load_ignore_pairs()
    
    results = []
    
    for file in files:
        if file.filename == '': continue
        
        img_bytes = file.read()
        try:
            res = logic.check_image_engine(img_bytes, DATABASE, DEFAULT_CFG, ignores)
            
            # Add filename to result for frontend mapping
            if res:
                res["filename"] = file.filename
                results.append(res)
            else:
                results.append({"filename": file.filename, "error": "Processing failed", "matches": []})
        except Exception as e:
            results.append({"filename": file.filename, "error": str(e), "matches": []})
    
    # Handle URLs
    urls = request.form.get('urls', '')
    if urls:
        import requests # Import here to avoid top-level dependency if preferred, or move up. Moving up is better style but this is safer for diff.
        for url in urls.split('\n'):
            url = url.strip()
            if not url: continue
            
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    img_bytes = resp.content
                    res = logic.check_image_engine(img_bytes, DATABASE, DEFAULT_CFG, ignores)
                    
                    if res:
                        res["filename"] = url
                        res["is_url"] = True
                        results.append(res)
                    else:
                        results.append({"filename": url, "error": "Processing failed", "matches": []})
                else:
                     results.append({"filename": url, "error": f"Download failed: {resp.status_code}", "matches": []})
            except Exception as e:
                results.append({"filename": url, "error": f"Error: {str(e)}", "matches": []})
    
    if not results:
        return jsonify({"error": "No valid files or URLs provided"}), 400
    
    return jsonify(results)

@app.route("/archive", methods=["POST"])
def archive():
    if 'file' not in request.files or 'client' not in request.form:
        return jsonify({"error": "Missing file or client"}), 400
    
    client = request.form['client']
    if client not in ["開源", "阿丹哥"]:
         return jsonify({"error": "Invalid client"}), 400

    file = request.files['file']
    img_bytes = file.read()
    
    path, sig = logic.add_db(img_bytes, client)
    
    if not path:
        return jsonify({"error": "Upload failed"}), 500

    # Update Memory DB
    try:
        if client not in DATABASE: DATABASE[client] = {}
        DATABASE[client][path] = sig
    except Exception as e:
        print(f"Error updating memory DB: {e}")

    return jsonify({"status": "success", "path": path})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
