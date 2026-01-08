import os
import json
import io
import shutil
import cv2
import numpy as np
import imagehash
from PIL import Image, ImageOps, ImageFile
from datetime import datetime
import uuid
import requests
import urllib.parse

# Allow loading truncated images
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import pytesseract
except ImportError:
    pytesseract = None

PAIRWISE_IGNORE_FILE = "ignore_pairs.json"
DB_ROOT = "./Database"

# ==========================================
# 0. Global State Helpers
# ==========================================

def load_ignore_pairs():
    if os.path.exists(PAIRWISE_IGNORE_FILE):
        try:
            with open(PAIRWISE_IGNORE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_ignore_pairs(pairs_dict):
    try:
        with open(PAIRWISE_IGNORE_FILE, 'w', encoding='utf-8') as f:
            json.dump(pairs_dict, f, ensure_ascii=False)
    except: pass

def add_ignore_pair(query_hash_str, db_path):
    pairs = load_ignore_pairs()
    if query_hash_str not in pairs:
        pairs[query_hash_str] = []
    if db_path not in pairs[query_hash_str]:
        pairs[query_hash_str].append(db_path)
        save_ignore_pairs(pairs)
    return True

# ==========================================
# 1. Core Visual Algorithms
# ==========================================

def standardize_image(pil_img):
    try:
        if pil_img.mode in ('RGBA', 'LA') or (pil_img.mode == 'P' and 'transparency' in pil_img.info):
            img = pil_img.convert("RGBA")
            background = Image.new("RGBA", img.size, (255, 255, 255))
            combined = Image.alpha_composite(background, img)
            return combined.convert("RGB")
        else:
            return pil_img.convert("RGB")
    except:
        return pil_img.convert("RGB")

def cv2_read_safe(file_path):
    try:
        if file_path.startswith("http"):
            resp = requests.get(file_path, timeout=10)
            if resp.status_code == 200:
                arr = np.asarray(bytearray(resp.content), dtype=np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return None
        else:
            stream = np.fromfile(file_path, dtype=np.uint8)
            img = cv2.imdecode(stream, cv2.IMREAD_COLOR)
            return img
    except Exception: return None

def auto_crop_borders(img_cv):
    try:
        if img_cv is None: return img_cv
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        top, bottom = 0, h
        threshold = 10 
        for y in range(h // 3):
            if np.std(gray[y, :]) < threshold: top = y
            else: break
        for y in range(h - 1, h * 2 // 3, -1):
            if np.std(gray[y, :]) < threshold: bottom = y
            else: break
        if bottom - top < 50: return img_cv
        return img_cv[top:bottom, 0:w]
    except: return img_cv

# Helper: Compute Normalized Histogram for Indexing
def compute_normalized_hist(img_pil):
    try:
        img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        img_cv = auto_crop_borders(img_cv)
        img_cv = cv2.resize(img_cv, (100, 100))
        hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist
    except: return None

def compute_image_signature(img_pil):
    """Computes Hash and Color Histogram for cache."""
    img_std = standardize_image(img_pil)
    phash = imagehash.phash(img_std)
    hist = compute_normalized_hist(img_std)
    return {
        "hash": phash,
        "hist": hist
    }

def check_akaze_features(img1_cv, img2_path):
    try:
        img2 = cv2_read_safe(img2_path)
        if img2 is None: return 0.0
        
        target_h = 600
        h1, w1 = img1_cv.shape[:2]
        h2, w2 = img2.shape[:2]
        
        img1 = cv2.resize(img1_cv, (int(w1 * (target_h/h1)), target_h))
        img2 = cv2.resize(img2, (int(w2 * (target_h/h2)), target_h))

        akaze = cv2.AKAZE_create()
        kp1, des1 = akaze.detectAndCompute(img1, None)
        kp2, des2 = akaze.detectAndCompute(img2, None)

        if des1 is None or des2 is None or len(des1) < 5 or len(des2) < 5:
            return 0.0

        bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        matches = bf.knnMatch(des1, des2, k=2)

        good_matches = []
        for m, n in matches:
            if m.distance < 0.8 * n.distance:
                good_matches.append(m)

        match_score = len(good_matches) / min(len(kp1), len(kp2))
        
        if len(good_matches) > 25:
            match_score = max(match_score, 0.85)
            
        return min(match_score, 1.0)
    except: return 0.0

def check_deep_scan_bidirectional(img_query, img_db_path):
    try:
        img_db = cv2_read_safe(img_db_path)
        if img_db is None: return 0.0
        
        img_db = auto_crop_borders(img_db)
        gray_q = cv2.cvtColor(img_query, cv2.COLOR_BGR2GRAY)
        gray_db = cv2.cvtColor(img_db, cv2.COLOR_BGR2GRAY)

        def scan_a_in_b(template, source):
            th, tw = template.shape
            sh, sw = source.shape
            if th > sh or tw > sw: return 0.0
            res = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return max_val

        best_val = 0.0
        scales = np.linspace(0.2, 2.0, 20)

        for s in scales:
            new_w = int(gray_db.shape[1] * s)
            new_h = int(gray_db.shape[0] * s)
            if new_w < 20 or new_h < 20: continue
            resized_db = cv2.resize(gray_db, (new_w, new_h))
            
            score1 = scan_a_in_b(gray_q, resized_db)
            score2 = scan_a_in_b(resized_db, gray_q)
            
            best_val = max(best_val, score1, score2)
            if best_val > 0.92: return best_val

        h_q, w_q = gray_q.shape
        h_d, w_d = gray_db.shape
        ratio_q = h_q / w_q
        ratio_d = h_d / w_d

        slices = []
        target = None
        
        if ratio_d > ratio_q * 1.5:
            step = h_d // 3
            slices = [gray_db[0:step*2, :], gray_db[step:step*3, :], gray_db[step//2 : h_d-step//2, :]]
            target = gray_q
        elif ratio_q > ratio_d * 1.5:
            step = h_q // 3
            slices = [gray_q[0:step*2, :], gray_q[step:step*3, :], gray_q[step//2 : h_q-step//2, :]]
            target = gray_db
            
        if slices and target is not None:
            for sl in slices:
                val = scan_a_in_b(target, sl) if target.shape[0] < sl.shape[0] else scan_a_in_b(sl, target)
                best_val = max(best_val, val)

        return best_val
    except: return 0.0

def check_spatial_color(img1_cv, img2_path):
    try:
        img2 = cv2_read_safe(img2_path)
        if img2 is None: return 0.0
        tiny1 = cv2.resize(img1_cv, (8, 8), interpolation=cv2.INTER_AREA)
        tiny2 = cv2.resize(img2, (8, 8), interpolation=cv2.INTER_AREA)
        lab1 = cv2.cvtColor(tiny1, cv2.COLOR_BGR2LAB).astype("float32")
        lab2 = cv2.cvtColor(tiny2, cv2.COLOR_BGR2LAB).astype("float32")
        diff = np.sqrt(np.sum((lab1 - lab2)**2, axis=2))
        return max(0, 1 - (np.mean(diff) / 60.0))
    except: return 0.0

def check_global_color(hist1, hist2):
    """
    Comparison using pre-computed histograms (O(1)).
    """
    try:
        if hist1 is None or hist2 is None: return 0.0
        return cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    except: return 0.0

def is_grayscale(img_cv):
    try:
        hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
        return np.mean(hsv[:, :, 1]) < 20 
    except: return False

def check_ocr_similarity(img1_cv, img2_path):
    if pytesseract is None: return 0.0
    try:
        img2 = cv2_read_safe(img2_path)
        if img2 is None: return 0.0
        gray1 = cv2.cvtColor(img1_cv, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        text1 = pytesseract.image_to_string(gray1, lang='chi_tra+eng').strip().replace(" ", "")
        text2 = pytesseract.image_to_string(gray2, lang='chi_tra+eng').strip().replace(" ", "")
        if len(text1) < 2 or len(text2) < 2: return 0.0
        set1, set2 = set(text1), set(text2)
        inter = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return inter / union if union > 0 else 0.0
    except: return 0.0

def is_sparse_image(img_cv):
    try:
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        return (np.sum(gray < 240) / (gray.shape[0] * gray.shape[1])) < 0.2
    except: return False

# ==========================================
# 2. Database & Engine
# ==========================================

CACHE_FILE = "index_cache.pkl"
BUCKET_NAME = "image_rec_resource"

def get_gcs_client():
    try:
        return storage.Client()
    except:
        return storage.Client.create_anonymous_client()

def save_index_cache(db):
    try:
        client = get_gcs_client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(CACHE_FILE)
        
        # Serialize and upload
        data = pickle.dumps(db)
        blob.upload_from_string(data)
        print("Index cache saved to GCS.")
    except Exception as e:
        print(f"Failed to save cache: {e}")

def load_index_cache():
    try:
        client = get_gcs_client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(CACHE_FILE)
        
        if blob.exists():
            data = blob.download_as_string()
            db = pickle.loads(data)
            print("Index cache loaded from GCS.")
            return db
    except Exception as e:
        print(f"Failed to load cache: {e}")
    return None

def load_database(progress_callback=None):
    # Try Cache First
    cached_db = load_index_cache()
    if cached_db:
        # Calculate total count
        total_in_cache = sum(len(v) for v in cached_db.values())
        
        if total_in_cache > 0:
            if progress_callback: progress_callback(total_in_cache)
            return cached_db, total_in_cache
        else:
            print("Cache found but empty. Forcing rebuild.")
            # Fall through to rebuild logic
    
    # Rebuild if no cache or empty cache
    db = {"阿丹哥": {}, "開源": {}}
    total = 0 # Initialize here to prevent UnboundLocalError
    
    # Rebuild if no cache or empty cache
    db = {"阿丹哥": {}, "開源": {}}
    total = 0 
    
    # Don't silence errors here; let main.py catch them
    client = get_gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    prefixes = ["阿丹哥/", "開源/"]
    
    for prefix in prefixes:
        blobs = bucket.list_blobs(prefix=prefix)
        client_name = prefix.strip("/")
        
        for blob in blobs:
            if blob.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                try:
                    safe_name = urllib.parse.quote(blob.name)
                    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{safe_name}"
                    
                    # Download once at startup
                    resp = requests.get(public_url, timeout=10)
                    if resp.status_code != 200: continue

                    img = Image.open(io.BytesIO(resp.content))
                    
                    # Compute Signature (Hash + Hist)
                    sig = compute_image_signature(img)
                    
                    db[client_name][public_url] = sig
                    total += 1
                    
                    if progress_callback:
                        progress_callback(total)
                        
                except Exception as e:
                    print(f"Error processing {blob.name}: {e}")
                    pass
    
    # Only save cache if we actually found something
    if total > 0:
        save_index_cache(db)
    else:
        print("Warning: Rebuild found 0 images. Not saving empty cache.")

    return db, total
        
    return db, total


def check_image_engine(image_input, database, cfg, ignore_pairs):
    if image_input is None: return None
    try:
        if isinstance(image_input, Image.Image): img_pil = image_input
        elif isinstance(image_input, bytes): img_pil = Image.open(io.BytesIO(image_input))
        else: img_pil = Image.open(image_input)
        
        # 1. Compute Query Signature
        sig_q = compute_image_signature(img_pil)
        target_hash = sig_q['hash']
        target_hist = sig_q['hist']
        target_hash_str = str(target_hash)
        
        # Prepare CV images for heavy checks (only if needed)
        img_std = standardize_image(img_pil)
        img_cv_original = cv2.cvtColor(np.array(img_std), cv2.COLOR_RGB2BGR)
        img_cv_clean = auto_crop_borders(img_cv_original)
        
        ignored_paths_for_this_img = ignore_pairs.get(target_hash_str, [])
        is_sparse = is_sparse_image(img_cv_original)
        is_query_bw = is_grayscale(img_cv_original)
        
        candidates = []
        
        # 2. In-Memory Scanning Loop
        for client, records in database.items():
            for path, sig_db in records.items():
                if path in ignored_paths_for_this_img: continue
                
                # Unwrap signature
                file_hash = sig_db['hash']
                file_hist = sig_db['hist']
                
                # Fast Checks
                h_diff = target_hash - file_hash
                global_c_score = 0.0
                
                if not is_sparse:
                    global_c_score = check_global_color(target_hist, file_hist)
                
                # 3. Filter using cached values
                if h_diff <= cfg.get('hash_cut', 35) or global_c_score > cfg.get('color_th', 0.55):
                    candidates.append({
                        'client': client, 'path': path, 
                        'h_diff': h_diff, 'global_c': global_c_score
                    })

        # Sort Logic
        candidates.sort(key=lambda x: x['global_c'], reverse=True)
        candidates = candidates[:25]

        matches = []
        debug_info = {"min_hash_diff": 100, "max_scan_score": 0.0, "max_spatial_score": 0.0, "max_ocr_score": 0.0, "max_akaze_score": 0.0}

        # 4. Heavy Checks Loop (Downloads happen here)
        for item in candidates:
            path = item['path']
            global_c = item['global_c']
            h_diff = item['h_diff']
            
            akaze_score = 0.0
            if cfg.get('use_scan', True): akaze_score = check_akaze_features(img_cv_clean, path)
            if akaze_score > debug_info["max_akaze_score"]: debug_info["max_akaze_score"] = akaze_score

            scan_score = 0.0
            if cfg.get('use_scan', True): scan_score = check_deep_scan_bidirectional(img_cv_clean, path)
            if scan_score > debug_info["max_scan_score"]: debug_info["max_scan_score"] = scan_score

            spatial_score = 0.0
            if cfg.get('use_color', True): spatial_score = check_spatial_color(img_cv_original, path)
            if spatial_score > debug_info["max_spatial_score"]: debug_info["max_spatial_score"] = spatial_score

            ocr_score = 0.0
            if cfg.get('use_ocr', False):
                 if is_sparse or (0.4 < max(global_c, spatial_score) < 0.85):
                     ocr_score = check_ocr_similarity(img_cv_original, path)
            if ocr_score > debug_info["max_ocr_score"]: debug_info["max_ocr_score"] = ocr_score

            is_match = False
            match_type = ""
            final_score_text = ""
            sort_val = 0
            
            veto = False
            if scan_score > 0.6 and spatial_score < 0.15:
                img_db = cv2_read_safe(path)
                is_db_bw = is_grayscale(img_db) if img_db is not None else False
                if not (is_query_bw and is_db_bw) and global_c < 0.4:
                    veto = True

            if not veto:
                if akaze_score > 0.35: 
                    is_match = True; match_type = "AKAZE"; final_score_text = f"{int(akaze_score*100)}%"; sort_val = int(akaze_score*100) + 70
                elif scan_score >= cfg.get('scan_th', 0.60):
                    is_match = True; match_type = "SCAN"; final_score_text = f"{int(scan_score*100)}%"; sort_val = int(scan_score*100) + 60
                elif spatial_score > 0.88:
                    is_match = True; match_type = "LAYOUT"; final_score_text = f"{int(spatial_score*100)}%"; sort_val = int(spatial_score*100) + 40
                elif ocr_score > 0.6 and max(scan_score, spatial_score) > 0.3:
                    is_match = True; match_type = "OCR"; final_score_text = f"{int(ocr_score*100)}%"; sort_val = int(ocr_score*100) + 30
                elif cfg.get('use_hash', True) and h_diff <= 15 and spatial_score > 0.5:
                    is_match = True; match_type = "HASH"; final_score_text = f"diff {h_diff}"; sort_val = 200 - h_diff

            if is_match:
                matches.append({
                    "client": item['client'], "path": path, 
                    "type": match_type, "score": final_score_text, "sort": sort_val,
                    "score_val": max(scan_score, spatial_score, ocr_score, akaze_score)
                })

        unique_map = {}
        for m in matches:
            p = m['path']
            if p not in unique_map or m['sort'] > unique_map[p]['sort']:
                unique_map[p] = m
        final_matches = sorted(list(unique_map.values()), key=lambda x: x["sort"], reverse=True)
        
        return {
            "img_hash": target_hash_str,
            "matches": final_matches,
            "debug": debug_info
        }
    except Exception as e:
        print(e)
        return None

def add_db(database, client, filename, img_bytes):
    from google.cloud import storage
    BUCKET_NAME = "image_rec_resource"
    
    # Generate unique name
    n = f"{client}/{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    
    try:
        try:
           storage_client = storage.Client()
        except:
           print("Cannot get storage client for upload")
           return None, None

        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(n)
        
        img = Image.open(io.BytesIO(img_bytes))
        
        # Compute signature before upload
        sig = compute_image_signature(img)
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        
        blob.upload_from_file(buf, content_type='image/png')
        
        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{n}"
        
        # Update RAM Database!
        if client not in database: database[client] = {}
        database[client][public_url] = sig
        
        return public_url, sig
    except Exception as e:
        print(f"Upload failed: {e}")
        return None, None
