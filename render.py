# render.py — Clarko TikTok Slide Renderer
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import os, subprocess, requests, tempfile, textwrap, traceback, shutil

app = Flask(__name__)

BG_COLOR     = (10, 10, 15)
ACCENT_COLOR = (99, 102, 241)
TEXT_COLOR   = (240, 240, 245)
MUTED_COLOR  = (120, 120, 140)
WIDTH, HEIGHT = 1080, 1920

def get_fonts():
    try:
        return (
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 44),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36),
        )
    except Exception as e:
        print(f"Font load failed: {e}")
        d = ImageFont.load_default()
        return d, d, d

def render_slide(slide_data, slide_num, total, fonts):
    font_big, font_med, font_sm = fonts
    img  = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (WIDTH, 10)], fill=ACCENT_COLOR)
    draw.text((WIDTH - 120, 40), f"{slide_num}/{total}", fill=MUTED_COLOR, font=font_sm)
    label = str(slide_data.get("label", "")).upper()
    draw.text((60, 140), label, fill=ACCENT_COLOR, font=font_sm)
    headline = str(slide_data.get("headline", ""))
    y = 240
    for line in textwrap.wrap(headline, width=18):
        draw.text((60, y), line, fill=TEXT_COLOR, font=font_big)
        y += 95
    subtext = str(slide_data.get("subtext", ""))
    if subtext:
        y += 20
        for line in textwrap.wrap(subtext, width=28):
            draw.text((60, y), line, fill=MUTED_COLOR, font=font_med)
            y += 58
    draw.rectangle([(0, HEIGHT - 100), (WIDTH, HEIGHT)], fill=(18, 18, 24))
    draw.text((60, HEIGHT - 72), "clarko.ai", fill=MUTED_COLOR, font=font_sm)
    return img

def make_video(slides_data, output_path):
    tmpdir = tempfile.mkdtemp()
    fonts  = get_fonts()
    clip_paths = []

    for i, slide in enumerate(slides_data):
        png_path  = os.path.join(tmpdir, f"slide_{i:03d}.png")
        clip_path = os.path.join(tmpdir, f"clip_{i:03d}.mp4")

        img = render_slide(slide, i + 1, len(slides_data), fonts)
        img.save(png_path)
        print(f"Saved PNG {i}: {os.path.getsize(png_path)} bytes")

        # Convert single PNG → 3-second video using pipe
        # Read PNG as raw RGB bytes and pipe into ffmpeg
        raw_bytes = img.tobytes()  # raw RGB
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-pixel_format", "rgb24",
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-framerate", "1",
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-t", "3",
            "-pix_fmt", "yuv420p",
            "-vf", "fps=24",
            clip_path
        ]
        result = subprocess.run(cmd, input=raw_bytes, capture_output=True)
        print(f"Clip {i} stderr: {result.stderr[-300:].decode('utf-8', errors='ignore')}")
        if result.returncode != 0:
            raise Exception(f"Slide {i} encode failed (code {result.returncode}): {result.stderr[-200:].decode('utf-8', errors='ignore')}")
        print(f"Clip {i}: {os.path.getsize(clip_path)} bytes")
        clip_paths.append(clip_path)

    # Concat all clips
    concat_file = os.path.join(tmpdir, "concat.txt")
    with open(concat_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Concat failed: {result.stderr[-300:]}")

    print(f"Final video: {os.path.getsize(output_path)} bytes")
    shutil.rmtree(tmpdir)
    return output_path


@app.route("/render", methods=["POST"])
def render_endpoint():
    try:
        data     = request.get_json(force=True)
        slides   = data.get("slides", [])
        caption  = data.get("caption", "")
        hashtags = data.get("hashtags", "")

        print(f"Received {len(slides)} slides")
        if not slides:
            return jsonify({"ok": False, "error": "No slides provided"}), 400

        out_path = f"/tmp/tiktok_{os.urandom(4).hex()}.mp4"
        make_video(slides, out_path)

        buffer_token   = os.environ["BUFFER_TOKEN"]
        buffer_channel = os.environ["BUFFER_CHANNEL_ID"]

        with open(out_path, "rb") as f:
            upload_resp = requests.post(
                "https://api.bufferapp.com/1/media/upload.json",
                headers={"Authorization": f"Bearer {buffer_token}"},
                files={"file": ("tiktok.mp4", f, "video/mp4")},
            )
        print(f"Buffer upload: {upload_resp.status_code} {upload_resp.text}")
        media_id = upload_resp.json().get("id")

        post_resp = requests.post(
            "https://api.bufferapp.com/1/updates/create.json",
            headers={"Authorization": f"Bearer {buffer_token}"},
            json={
                "profile_ids": [buffer_channel],
                "text": f"{caption}\n\n{hashtags}",
                "media": {"video_id": media_id},
                "now": "true"
            }
        )
        print(f"Buffer post: {post_resp.status_code} {post_resp.text}")
        os.remove(out_path)
        return jsonify({"ok": True, "buffer": post_resp.json()})

    except Exception as e:
        tb = traceback.format_exc()
        print(f"ERROR: {tb}")
        return jsonify({"ok": False, "error": str(e), "traceback": tb}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
