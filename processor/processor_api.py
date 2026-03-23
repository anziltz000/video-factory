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
ASSETS_DIR     = "/app/assets/campaign-logos"

os.makedirs(WORKSPACE_DIR, exist_ok=True)

# ──────────────────────────────────────────────
#  CAMPAIGN CONFIG
# ──────────────────────────────────────────────
CAMPAIGN_CONFIG = {
    "leonbet": {"file": "LEONBET-LOGO.mp4",  "type": "video", "chroma": "0x0000FF"},
    "bitz":    {"file": "Bitz.io-LOGO.mp4",  "type": "video", "chroma": "0x00FF00"},
    "acebet":  {"file": "ACEBET-LOGO.mp4",   "type": "video", "chroma": "0x0000FF"},
    "rajbet":  {"file": "RajBet-LOGO.mp4",   "type": "video", "chroma": "0x0000FF"},
}

LOGO_WIDTH = 550

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
        raise FileNotFoundError(f"Logo not found: {path}")
    return path

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
            "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info    = ydl.extract_info(video_url, download=True)
            caption = info.get("description") or info.get("title") or "No caption"

        # ── Step 2: FFmpeg processing ──────────
        print(f"⚙️  [2/3] Rendering | campaign={campaign_key} | position={position_key}", flush=True)
        probe     = ffmpeg.probe(input_path)
        has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])

        base = (
            ffmpeg.input(input_path)
            .filter("scale", 1080, 1920, force_original_aspect_ratio="decrease", flags="lanczos")
            .filter("pad", 1080, 1920, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .filter("setsar", 1)
        )

        cfg       = CAMPAIGN_CONFIG[campaign_key]
        logo_file = asset_path(campaign_key)
        overlay   = (
            ffmpeg.input(logo_file, stream_loop=-1)
            .filter("colorkey", cfg["chroma"], 0.30, 0.15)
            .filter("scale", LOGO_WIDTH, -2)
        )

        x_val, y_val = POS_MAP.get(position_key, POS_MAP["bottom"])
        composited   = base.overlay(overlay, x=x_val, y=y_val, shortest=1)

        encode_kwargs = {
            "vcodec":   "libx264",
            "pix_fmt":  "yuv420p",
            "crf":      "18",
            "preset":   "medium",
            "threads":  "4",
            "movflags": "+faststart",
        }

        if has_audio:
            audio = ffmpeg.input(input_path).audio
            out   = ffmpeg.output(composited, audio, output_path, **encode_kwargs, acodec="copy")
        else:
            out   = ffmpeg.output(composited, output_path, **encode_kwargs)

        print("🎬  Encoding…", flush=True)
        ffmpeg.run(out, overwrite_output=True, capture_stdout=True, capture_stderr=True)

        # ── Step 3: Send to n8n ───────────────
        print(f"🚀 [3/3] Sending to n8n webhook: {reply_webhook_url}", flush=True)
        file_size = os.path.getsize(output_path)
        print(f"    Output size: {file_size / 1_000_000:.1f} MB", flush=True)

        with open(output_path, "rb") as f:
            response = requests.post(
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
            response.raise_for_status()

        print(f"✅ Delivery complete! n8n status: {response.status_code}", flush=True)

    except Exception as e:
        print(f"❌ Error: {e}", flush=True)

    finally:
        for path in (input_path, output_path):
            if os.path.exists(path):
                os.remove(path)
        print("🧹 Cleaned up temp files.", flush=True)

# ──────────────────────────────────────────────
#  QUEUE + WORKER & HTTP API
# ──────────────────────────────────────────────
task_queue: queue.Queue = queue.Queue()

def _worker():
    while True:
        task = task_queue.get()
        if task is None: break
        process_task(task["url"], task["campaign"], task["position"], task["target"], task["webhook_reply_url"])
        task_queue.task_done()

threading.Thread(target=_worker, daemon=True, name="video-worker").start()

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "online", "queue_size": task_queue.qsize()}), 200

@app.route("/process", methods=["POST"])
def enqueue():
    data = request.get_json(force=True, silent=True) or {}
    
    # Required keys
    video_url         = data.get("url")
    reply_webhook_url = data.get("webhook_reply_url")
    
    if not video_url or not reply_webhook_url:
        return jsonify({"error": "Missing url or webhook_reply_url"}), 400

    task_queue.put({
        "url":               video_url,
        "campaign":          data.get("campaign", "leonbet").lower(),
        "position":          data.get("position", "bottom").lower(),
        "target":            data.get("target", "both").lower(),
        "webhook_reply_url": reply_webhook_url,
    })

    return jsonify({"message": "Queued!", "queue_position": task_queue.qsize()}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=False)
