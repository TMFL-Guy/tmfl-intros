#!/usr/bin/env python3
"""Generate a short image-to-video clip using the public Wan 2.2 Gradio Space.

Based on the public API contract documented in IgorCSIS/nifty-vid.
No API keys or paid services. Public shared GPU availability is not guaranteed.
"""
import json
import os
import pathlib
import sys
import time
from urllib.parse import urlparse

import requests
from PIL import Image, ImageFilter

BASE = "https://cbensimon-wan2-2-fp8da-aoti-preview2.hf.space"
FN = "generate_video"
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)
SESSION = requests.Session()
NEGATIVE = ("色调艳丽, 过曝, 静态, 细节模糊不清, 字幕, 风格, 作品, 画作, 画面, 静止, 整体发灰, "
            "最差质量, 低质量, JPEG压缩残留, 丑陋的, 残缺的, 多余的手指, 画得不好的手部, "
            "画得不好的脸部, 畸形的, 毁容的, 形态畸形的肢体, 手指融合, 静止不动的画面, "
            "杂乱的背景, 三条腿, 背景人很多, 倒着走")

def check_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Image URL must be a direct HTTPS URL.")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Local URLs are not allowed.")
    return url

def prepare_image():
    url = os.environ.get("INPUT_IMAGE_URL", "").strip()
    target = OUT / "input.png"
    if url:
        print("Downloading input image from supplied URL...", flush=True)
        r = SESSION.get(check_url(url), timeout=40, allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MB.")
        target.write_bytes(r.content)
    else:
        for name in ("assets/scene.png", "assets/scene.jpg", "halloween-classic.png", "ChatGPT Image Oct 30, 2026, 05_17_08 PM.png"):
            candidate = ROOT / name
            if candidate.exists():
                target.write_bytes(candidate.read_bytes())
                print(f"Using repository image: {name}", flush=True)
                break
        else:
            raise ValueError("No image found. Provide image_url, or add assets/scene.png to the repository.")
    with Image.open(target) as img:
        rgb = img.convert("RGB")
        # Lower source resolution reduces memory use on the free shared GPU.
        max_width = int(os.environ.get("MAX_INPUT_WIDTH", "832"))
        max_height = int(os.environ.get("MAX_INPUT_HEIGHT", "480"))
        frame_w, frame_h = 832, 468
        scale = max(frame_w / rgb.width, frame_h / rgb.height)
        bg = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.Resampling.LANCZOS)
        x, y = (bg.width-frame_w)//2, (bg.height-frame_h)//2
        bg = bg.crop((x,y,x+frame_w,y+frame_h)).filter(ImageFilter.GaussianBlur(24))
        rgb.thumbnail((frame_w,frame_h), Image.Resampling.LANCZOS)
        bg.paste(rgb, ((frame_w-rgb.width)//2,(frame_h-rgb.height)//2))
        rgb = bg
        rgb.save(target, "PNG", optimize=True)
        print(f"Prepared video source: {rgb.width}x{rgb.height}", flush=True)
    if target.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Converted image exceeds 8 MB; use a smaller image.")
    return target

def upload(path):
    with path.open("rb") as f:
        r = SESSION.post(f"{BASE}/gradio_api/upload", files={"files": (path.name, f, "image/png")}, timeout=120)
    r.raise_for_status()
    paths = r.json()
    if not isinstance(paths, list) or not paths:
        raise RuntimeError(f"Unexpected upload response: {paths!r}")
    return paths[0]

def generate(image_path, prompt, duration):
    file_data = {
        "path": image_path,
        "url": f"{BASE}/gradio_api/file={image_path}",
        "orig_name": "input.png",
        "size": None,
        "mime_type": None,
        "meta": {"_type": "gradio.FileData"},
    }
    data = [file_data, None, prompt, 6, NEGATIVE, duration, 1, 1, 42,
            True, 6, "UniPCMultistep", 3.0, 16, False, True]
    r = SESSION.post(f"{BASE}/gradio_api/call/{FN}", json={"data": data}, timeout=120)
    r.raise_for_status()
    event_id = r.json().get("event_id")
    if not event_id:
        raise RuntimeError("Upstream returned no event_id.")
    print(f"Submitted job: {event_id}", flush=True)
    with SESSION.get(f"{BASE}/gradio_api/call/{FN}/{event_id}",
                     headers={"Accept": "text/event-stream"}, stream=True, timeout=(30, 540)) as stream:
        stream.raise_for_status()
        event = "message"
        chunks = []
        for line in stream.iter_lines(decode_unicode=True):
            if line is None:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                chunks.append(line[5:].strip())
            elif not line.strip():
                if event == "complete":
                    payload = json.loads("\n".join(chunks))
                    first = payload[0] if isinstance(payload, list) and payload else None
                    if isinstance(first, str):
                        return f"{BASE}/gradio_api/file={first}"
                    if isinstance(first, dict):
                        return first.get("url") or f"{BASE}/gradio_api/file={first['path']}"
                    raise RuntimeError("Generation completed without a video file.")
                if event == "error":
                    raise RuntimeError("Upstream error: " + "\n".join(chunks))
                event, chunks = "message", []
    raise RuntimeError("Upstream stream closed without a completed video.")

def main():
    try:
        prompt = os.environ.get("INPUT_PROMPT", "").strip()
        if not prompt:
            raise ValueError("Motion prompt is required.")
        duration = float(os.environ.get("INPUT_DURATION", "3.5"))
        if not 0.5 <= duration <= 4.5:
            raise ValueError("Duration must be between 0.5 and 4.5 seconds.")
        image = prepare_image()
        path = upload(image)
        print("Waiting for public GPU to render clip...", flush=True)
        video_url = generate(path, prompt, duration)
        print("Downloading generated MP4...", flush=True)
        r = SESSION.get(check_url(video_url), timeout=180)
        r.raise_for_status()
        if not r.content or not (r.content[4:8] == b"ftyp"):
            raise RuntimeError("Upstream returned a file that is not a valid MP4 container.")
        output = OUT / "tmfl-stadium-awakens.mp4"
        output.write_bytes(r.content)
        import subprocess
        landscape = OUT / "tmfl-stadium-awakens-landscape.mp4"
        vf = "scale=832:468:force_original_aspect_ratio=decrease,pad=832:468:(ow-iw)/2:(oh-ih)/2,setsar=1"
        if os.environ.get("HALLWAY_TRANSITION") == "1":
            # Blackout is applied in post, not left to the video model.
            # Fade for 0.2s, then guarantee pure black for the final 0.1s.
            vf += f",fade=t=out:st={max(0, duration-0.30):.3f}:d=0.20"
            vf += f",drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='gte(t,{max(0, duration-0.10):.3f})'"
        subprocess.run(["ffmpeg","-y","-i",str(output),"-vf",vf,"-an","-c:v","libx264","-pix_fmt","yuv420p",str(landscape)],check=True)
        output.unlink()
        output = landscape
        (OUT / "status.txt").write_text(f"SUCCESS: {output.name} ({len(r.content)} bytes)\n")
        print(f"SUCCESS: {output} ({len(r.content)} bytes)", flush=True)
    except Exception as exc:
        (OUT / "status.txt").write_text(f"FAILED: {type(exc).__name__}: {exc}\n")
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
