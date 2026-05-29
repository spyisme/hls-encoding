import os
import re
import math
import time
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import requests
import httpx
from dotenv import load_dotenv

# ==========================================
# CONFIG
# ==========================================

load_dotenv()

app = Flask(__name__, static_folder=None)

PORT = int(os.getenv('PORT', 3000))
UPLOAD_DIR = Path(__file__).parent / 'uploads'
PUBLIC_DIR = Path(__file__).parent / 'templates'
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB

# In-memory job tracker
jobs: dict[str, dict] = {}


def generate_job_id() -> str:
    """Generate a short unique job ID matching the Node version's format."""
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex[:5]
    # Base-36 encode the timestamp
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    result = ''
    while ts:
        result = chars[ts % 36] + result
        ts //= 36
    return result + rand


def dispatch_github_action(payload: dict):
    """Trigger a GitHub Actions repository_dispatch event."""
    url = f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/dispatches"
    headers = {
        'Authorization': f"token {os.getenv('GITHUB_PAT')}",
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()


# ==========================================
# GOOGLE DRIVE AUDIT
# ==========================================

def get_gdrive_link_id(file_id: str) -> str:
    """Extract the Google Drive file ID from a URL or return as-is if already an ID."""
    if 'drive.google.com' in file_id:
        match = re.search(r'/d/([^/]+)', file_id) or re.search(r'id=([^&]+)', file_id)
        return match.group(1) if match else file_id
    return file_id


def format_drive_bytes(byte_count: int) -> str | None:
    """Format bytes into a human-readable string."""
    if byte_count is None or byte_count <= 0:
        return None
    sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    i = int(math.floor(math.log(byte_count, 1024)))
    return f"{round(byte_count / (1024 ** i), 2)} {sizes[i]}"


async def custom_drive_audit(file_id: str) -> dict:
    """
    Check if a Google Drive file is publicly accessible and extract metadata.
    Returns dict with: id, name, size, sizeFound
    """
    drive_id = get_gdrive_link_id(file_id)
    download_url = f"https://drive.google.com/uc?export=download&id={drive_id}"

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.8',
        }

        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            # Hop 1: Initial Handshake
            response = await client.get(download_url, headers=headers)

            cookies = dict(response.cookies)
            redirect_url = response.headers.get('location', '')

            if 'ServiceLogin' in redirect_url or 'accounts.google.com' in redirect_url:
                return {'id': drive_id, 'name': 'Private Asset', 'size': 'Locked', 'sizeFound': False}

            # Hop 2: Session Validation
            if cookies:
                headers['Cookie'] = '; '.join(f'{k}={v}' for k, v in cookies.items())

            next_target = redirect_url or download_url
            final_response = await client.get(next_target, headers=headers, follow_redirects=True)
            content_type = final_response.headers.get('content-type', '')
            html_body = final_response.text

        # Standard private/deleted block
        if any(marker in html_body for marker in ['You need access', 'Request access', 'item-not-found-page']):
            return {'id': drive_id, 'name': 'Hidden File', 'size': 'Locked', 'sizeFound': False}

        file_name = 'Unknown File'

        # CONDITION 1: Virus scan warning screen (large file)
        if 'text/html' in content_type and ('Virus scan warning' in html_body or 'uc-main' in html_body):
            extracted_size = None

            text_block_match = re.search(r'<span class="uc-name-size">([\s\S]*?)</span>', html_body)
            if text_block_match:
                inner_html = text_block_match.group(1)

                name_match = re.search(r'>([^<]+)</a>', inner_html)
                if name_match:
                    file_name = name_match.group(1).strip()

                size_match = re.search(r'\(([^)]+)\)', inner_html)
                if size_match:
                    extracted_size = size_match.group(1).strip()

            if file_name == 'Unknown File':
                title_match = re.search(r'<title>([^<]+)</title>', html_body)
                if title_match:
                    file_name = title_match.group(1).replace(' - Google Drive', '').strip()

            if extracted_size:
                return {'id': drive_id, 'name': file_name, 'size': extracted_size, 'sizeFound': True}
            else:
                return {'id': drive_id, 'name': file_name, 'size': 'Unknown Size', 'sizeFound': False}

        # CONDITION 2: Small file (direct binary payload)
        content_length = final_response.headers.get('content-length')
        calculated_size = format_drive_bytes(int(content_length)) if content_length else None

        title_match = re.search(r'<title>([^<]+)</title>', html_body)
        if title_match:
            file_name = title_match.group(1).replace(' - Google Drive', '').strip()

        if calculated_size:
            return {'id': drive_id, 'name': file_name, 'size': calculated_size, 'sizeFound': True}
        else:
            return {'id': drive_id, 'name': file_name, 'size': 'Unknown Size', 'sizeFound': False}

    except Exception:
        return {'id': drive_id, 'name': 'Error Context', 'size': 'Unknown', 'sizeFound': False}


# ==========================================
# STATIC FILES — serve from ../public/
# ==========================================

@app.route('/')
def index():
    return send_from_directory(PUBLIC_DIR, 'index.html')


@app.route('/<path:filename>')
def static_files(filename):
    # Try public dir first, then uploads
    if (PUBLIC_DIR / filename).is_file():
        return send_from_directory(PUBLIC_DIR, filename)
    return '', 404


@app.route('/uploads/<path:filename>')
def uploaded_files(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ==========================================
# API ROUTES
# ==========================================

# ---------- File Upload ----------

@app.route('/api/upload', methods=['POST'])
def upload_video():
    try:
        if 'video' not in request.files:
            return jsonify({'error': 'No video file uploaded.'}), 400

        file = request.files['video']
        if file.filename == '':
            return jsonify({'error': 'No video file uploaded.'}), 400

        # Save file
        original_name = secure_filename(file.filename)
        unique_name = f"{int(time.time() * 1000)}-{original_name}"
        save_path = UPLOAD_DIR / unique_name
        file.save(str(save_path))

        output_name = request.form.get('outputName') or Path(original_name).stem
        parent_folder = request.form.get('parentFolder') or 'videos'
        server_url = os.getenv('SERVER_PUBLIC_URL', '').strip()
        video_url = f"{server_url}/uploads/{unique_name}"
        callback_webhook = f"{server_url}/api/webhook/complete"

        job_id = generate_job_id()

        # Trigger GitHub Actions
        dispatch_github_action({
            'event_type': 'trigger-encode',
            'client_payload': {
                'video_url': video_url,
                'output_name': output_name,
                'parent_folder': parent_folder,
                'callback_webhook': callback_webhook,
                'job_id': job_id,
                'source_type': 'direct',
            }
        })

        # Store job
        jobs[job_id] = {
            'id': job_id,
            'outputName': output_name,
            'parentFolder': parent_folder,
            'originalFile': file.filename,
            'localFile': unique_name,
            'source': 'upload',
            'status': 'dispatched',
            'startedAt': datetime.now(timezone.utc).isoformat(),
            'completedAt': None,
            'timeTaken': None,
        }

        return jsonify({'success': True, 'jobId': job_id, 'message': 'Encoding job dispatched to GitHub Actions.'})

    except requests.exceptions.RequestException as e:
        detail = str(e)
        print(f"Dispatch error: {detail}")
        return jsonify({'error': 'Failed to dispatch encoding job.', 'details': detail}), 500
    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({'error': 'Failed to dispatch encoding job.', 'details': str(e)}), 500


# ---------- Google Drive Upload ----------

@app.route('/api/g-drive/upload', methods=['POST'])
def gdrive_upload():
    try:
        data = request.get_json(force=True)
        drive_url = data.get('driveUrl', '').strip()
        output_name = data.get('outputName', '').strip()
        parent_folder = data.get('parentFolder', '').strip()

        if not drive_url:
            return jsonify({'error': 'No Google Drive URL provided.'}), 400

        # Step 1: Extract file ID and validate
        file_id = get_gdrive_link_id(drive_url)
        if not file_id or file_id == drive_url:
            return jsonify({'error': 'Invalid Google Drive URL. Please provide a valid sharing link.'}), 400

        print(f"\n🔍 Verifying Google Drive file accessibility: {file_id}")

        # Run the async audit in a sync context
        audit = asyncio.run(custom_drive_audit(drive_url))

        if not audit.get('sizeFound'):
            print(f"❌ File not accessible: {audit['name']} — {audit['size']}")
            return jsonify({
                'error': 'File is not accessible. Please check the sharing permissions.',
                'details': {
                    'fileName': audit['name'],
                    'status': audit['size'],
                    'fileId': audit['id'],
                }
            }), 403

        print(f"✅ File verified: {audit['name']} ({audit['size']})")

        # Step 2: Dispatch GitHub Actions
        resolved_output = output_name or re.sub(r'[^a-zA-Z0-9\-_]', '-', re.sub(r'\.[^.]+$', '', audit['name'])) or 'gdrive-video'
        resolved_folder = parent_folder or 'videos'
        server_url = os.getenv('SERVER_PUBLIC_URL', '').strip()
        callback_webhook = f"{server_url}/api/webhook/complete"
        job_id = generate_job_id()

        dispatch_github_action({
            'event_type': 'trigger-encode',
            'client_payload': {
                'source_type': 'gdrive',
                'gdrive_file_id': file_id,
                'gdrive_file_name': audit['name'],
                'output_name': resolved_output,
                'parent_folder': resolved_folder,
                'callback_webhook': callback_webhook,
                'job_id': job_id,
            }
        })

        # Store job
        jobs[job_id] = {
            'id': job_id,
            'outputName': resolved_output,
            'parentFolder': resolved_folder,
            'originalFile': f"[GDrive] {audit['name']}",
            'localFile': None,
            'source': 'gdrive',
            'driveFileId': file_id,
            'driveFileSize': audit['size'],
            'status': 'dispatched',
            'startedAt': datetime.now(timezone.utc).isoformat(),
            'completedAt': None,
            'timeTaken': None,
        }

        return jsonify({
            'success': True,
            'jobId': job_id,
            'message': 'Google Drive encoding job dispatched to GitHub Actions.',
            'fileInfo': {'name': audit['name'], 'size': audit['size'], 'id': file_id},
        })

    except requests.exceptions.RequestException as e:
        detail = str(e)
        print(f"GDrive dispatch error: {detail}")
        return jsonify({'error': 'Failed to dispatch Google Drive encoding job.', 'details': detail}), 500
    except Exception as e:
        print(f"GDrive error: {e}")
        return jsonify({'error': 'Failed to dispatch Google Drive encoding job.', 'details': str(e)}), 500


# ---------- Webhook (GitHub Actions callback) ----------

@app.route('/api/webhook/complete', methods=['POST'])
def webhook_complete():
    data = request.get_json(force=True)
    status = data.get('status', '')
    output_name = data.get('output_name', '')
    time_taken = data.get('time_taken_seconds', '')

    print(f"\n✅ Webhook received: {output_name} — Status: {status} — Time: {time_taken}s")

    for job_id, job in jobs.items():
        if job['outputName'] == output_name and job['status'] == 'dispatched':
            job['status'] = 'completed' if status == 'success' else 'failed'
            job['completedAt'] = datetime.now(timezone.utc).isoformat()
            job['timeTaken'] = f"{time_taken}s" if time_taken else 'unknown'

            # Clean up local file (only for direct uploads)
            if job.get('localFile'):
                local_path = UPLOAD_DIR / job['localFile']
                if local_path.exists():
                    local_path.unlink()
                    print(f"🗑️  Cleaned up source file: {job['localFile']}")
            break

    return jsonify({'received': True})


# ---------- Jobs list ----------

@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    all_jobs = sorted(jobs.values(), key=lambda j: j['startedAt'], reverse=True)
    return jsonify(all_jobs)


# ---------- Health check ----------

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'online',
        'uptime': time.monotonic(),
        'jobCount': len(jobs),
    })


# ==========================================
# START SERVER
# ==========================================

if __name__ == '__main__':
    server_url = os.getenv('SERVER_PUBLIC_URL', 'N/A')
    repo = f"{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}"

    print(f"\n🚀 HLS Encoding Dashboard running at http://localhost:{PORT}")
    print(f"📡 Webhook endpoint: {server_url}/api/webhook/complete")
    print(f"📂 Repo target: {repo}\n")

    app.run(host='0.0.0.0', port=PORT, debug=False)
