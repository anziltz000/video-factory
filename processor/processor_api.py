import os
import time
import threading
import queue
import requests
import ffmpeg
import numpy as np
import cv2
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

# ──────────────────────────────────────────────
#  PATHS
# ──────────────────────────────────────────────
WORKSPACE_DIR  = "/tmp/workspace"
ASSETS_DIR     = "/app/assets/campaign-logos"   # mounted from host

os.makedirs(WORKSPACE_DIR, exist_ok=True)

# ──────────────────────────────────────────────
#  CAMPAIGN CONFIG  (local files only, no Cloudinary)
# ──────────────────────────────────────────────
# Place the logo .mp4 files in  assets/campaign-logos/  on the host.
# chroma key colour:
#   Blue screen → 0x0000FF
#   Green screen → 0x00FF00
CAMPAIGN_CONFIG = {
    "leonbet": {
        "file":   "LEONBET-LOGO.mp4",
        "type":   "video",
        "chroma": "0x0000FF",   # blue screen
    },
    "bitz": {
        "file":   "Bitz.io-LOGO.mp4",
        "type":   "video",
        "chroma": "0x00FF00",   # green screen
    },
    "acebet": {
        "file":   "ACEBET-LOGO.mp4",
        "type":   "video",
        "chroma": "0x0000FF",
    },
    "rajbet": {
        "file":   "RajBet-LOGO.mp4",
        "type":   "video",
        "chroma": "0x0000FF",
    },
}

# Logo overlay width (px). Height scales automatically.
LOGO_WIDTH = 550

# ──────────────────────────────────────────────
#  LOGO POSITION MAP
# ──────────────────────────────────────────────
POS_MAP = {
    "top":    ("(main_w-overlay_w)/2", "80"),
    "bottom": ("(main_w-overlay_w)/2", "main_h-overlay_h-80"),
    "c1":     ("40",                   "80"),
    "c2":     ("main_w-overlay_w-40",  "main_h-overlay_h-80"),
}

# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def asset_path(campaign_key: str) -> str:
    cfg  = CAMPAIGN_CONFIG[campaign_key]
    path = os.path.join(ASSETS_DIR, cfg["file"])
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Logo not found: {path}\n"
            f"Put '{cfg['file']}' in the assets/campaign-logos/ folder."
        )
    return path

def get_brightness(video_path: str) -> float:
    """Sample 10 frames and return mean brightness (0–255)."""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 128.0
        vals = []
        for _ in range(10):
            ret, frame = cap.read()
            if not ret:
                break
            vals.append(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))
        cap.release()
        return float(np.mean(vals)) if vals else 128.0
    except Exception as e:
        print(f"[WARN] Brightness check failed: {e}", flush=True)
        return 128.0

# ──────────────────────────────────────────────
#  CORE PROCESSING FUNCTION
# ──────────────────────────────────────────────
def process_task(video_url, campaign_key, position_key, target_key, reply_webhook_url):
    ts         = int(time.time())
    input_path = os.path.join(WORKSPACE_DIR, f"raw_{ts}.mp4")
    output_path= os.path.join(WORKSPACE_DIR, f"final_{ts}.mp4")
    caption    = "No caption found"

    try:
        # ── Step 1: Download ───────────────────
        print(f"📥 [1/3] Downloading: {video_url}", flush=True)
        ydl_opts = {
            "outtmpl":              input_path,
            "format":               "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format":  "mp4",
            "quiet":                True,
            "no_warnings":          True,
            "postprocessors": [{
                "key":            "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info    = ydl.extract_info(video_url, download=True)
            caption = info.get("description") or info.get("title") or "No caption"

        # ── Step 2: FFmpeg processing ──────────
        print(f"⚙️  [2/3] Rendering | campaign={campaign_key} | position={position_key}", flush=True)

        probe     = ffmpeg.probe(input_path)
        has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])

        # Scale + pad to 1080×1920 (Shorts / Reels format), keep SAR
        base = (
            ffmpeg.input(input_path)
            .filter("scale", 1080, 1920,
                    force_original_aspect_ratio="decrease",
                    flags="lanczos")                        # lanczos = sharper upscale
            .filter("pad", 1080, 1920,
                    "(ow-iw)/2", "(oh-ih)/2",
                    color="black")
            .filter("setsar", 1)                            # fix pixel aspect ratio
        )

        # Logo overlay
        cfg  = CAMPAIGN_CONFIG[campaign_key]
        logo_file = asset_path(campaign_key)

        overlay = (
            ffmpeg.input(logo_file, stream_loop=-1)         # loop logo if shorter than video
            .filter("colorkey", cfg["chroma"], 0.30, 0.15)  # tighter tolerance = cleaner key
            .filter("scale", LOGO_WIDTH, -2)
        )

        x_val, y_val = POS_MAP.get(position_key, POS_MAP["bottom"])
        composited   = base.overlay(overlay, x=x_val, y=y_val, shortest=1)

        # ── High-quality encode settings ──
        # Oracle A1 has 4 ARM cores → use threads=4
        # CRF 18 = high quality (lower = better, 0 = lossless)
        # preset "medium" = good speed/quality balance (was "ultrafast" before)
        encode_kwargs = {
            "vcodec":   "libx264",
            "pix_fmt":  "yuv420p",      # maximum compatibility
            "crf":      "18",           # high quality (was 25)
            "preset":   "medium",       # good quality (was ultrafast)
            "threads":  "4",            # use all 4 Oracle ARM cores
            "movflags": "+faststart",   # web-optimised: moov atom at front
            # NO fps cap — keep original source fps
            # NO duration cap  — keep full video
        }

        if has_audio:
            audio = ffmpeg.input(input_path).audio
            out   = ffmpeg.output(composited, audio, output_path,
                                  **encode_kwargs, acodec="copy")   # copy audio = lossless + faster
        else:
            out   = ffmpeg.output(composited, output_path, **encode_kwargs)

        print("🎬  Encoding…", flush=True)
        ffmpeg.run(out, overwrite_output=True,
                   capture_stdout=True, capture_stderr=True)

        # ── Step 3: Send to n8n ───────────────
        print(f"🚀 [3/3] Sending to n8n webhook…", flush=True)
        file_size = os.path.getsize(output_path)
        print(f"    Output size: {file_size / 1_000_000:.1f} MB", flush=True)

        with open(output_path, "rb") as f:
            requests.post(
                reply_webhook_url,
                files={"file": (os.path.basename(output_path), f, "video/mp4")},
                data={
                    "campaign": campaign_key,
                    "position": position_key,
                    "target":   target_key,
                    "caption":  caption,
                },
                timeout=120,
            )

        print("✅ Delivery complete!", flush=True)

    except FileNotFoundError as e:
        print(f"❌ Asset error: {e}", flush=True)
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
        print(f"❌ FFmpeg error:\n{stderr}", flush=True)
    except Exception as e:
        print(f"❌ Processing error: {e}", flush=True)

    finally:
        for path in (input_path, output_path):
            if os.path.exists(path):
                os.remove(path)
        print("🧹 Cleaned up temp files.", flush=True)

# ──────────────────────────────────────────────
#  QUEUE + WORKER
# ──────────────────────────────────────────────
task_queue: queue.Queue = queue.Queue()

def _worker():
    print("🔧 Worker thread started.", flush=True)
    while True:
        task = task_queue.get()
        if task is None:
            break
        print(f"🚦 Processing task: campaign={task['campaign']} target={task['target']}", flush=True)
        process_task(
            task["url"],
            task["campaign"],
            task["position"],
            task["target"],
            task["webhook_reply_url"],
        )
        task_queue.task_done()

threading.Thread(target=_worker, daemon=True, name="video-worker").start()

# ──────────────────────────────────────────────
#  HTTP API
# ──────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "online", "queue_size": task_queue.qsize()}), 200

@app.route("/process", methods=["POST"])
def enqueue():
    data = request.get_json(force=True, silent=True) or {}

    video_url         = data.get("url")
    campaign_key      = data.get("campaign",  "leonbet").lower()
    position_key      = data.get("position",  "bottom").lower()
    target_key        = data.get("target",    "both").lower()
    reply_webhook_url = data.get("webhook_reply_url")

    if not video_url:
        return jsonify({"error": "Missing 'url'"}), 400
    if not reply_webhook_url:
        return jsonify({"error": "Missing 'webhook_reply_url'"}), 400
    if campaign_key not in CAMPAIGN_CONFIG:
        return jsonify({"error": f"Unknown campaign '{campaign_key}'"}), 400

    task_queue.put({
        "url":               video_url,
        "campaign":          campaign_key,
        "position":          position_key,
        "target":            target_key,
        "webhook_reply_url": reply_webhook_url,
    })

    q_size = task_queue.qsize()
    print(f"📋 Task queued. Queue depth: {q_size}", flush=True)
    return jsonify({"message": "Queued!", "queue_position": q_size}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=False)
