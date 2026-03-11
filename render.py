# render.py — Clarko TikTok Slide Renderer (image-only, no ffmpeg)
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import os, requests, tempfile, textwrap, traceback, base64

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

        fonts = get_fonts()
        tmpdir = tempfile.mkdtemp()

        # Render each slide as a PNG and upload to Buffer as images
        buffer_token   = os.environ["BUFFER_TOKEN"]
        buffer_channel = os.environ["BUFFER_CHANNEL_ID"]

        media_ids = []
        for i, slide in enumerate(slides):
            img = render_slide(slide, i + 1, len(slides), fonts)
            png_path = os.path.join(tmpdir, f"slide_{i}.png")
            img.save(png_path)
            print(f"Slide {i}: {os.path.getsize(png_path)} bytes")

            with open(png_path, "rb") as f:
                upload_resp = requests.post(
                    "https://api.bufferapp.com/1/media/upload.json",
                    headers={"Authorization": f"Bearer {buffer_token}"},
                    files={"file": (f"slide_{i}.png", f, "image/png")},
                )
            print(f"Upload {i}: {upload_resp.status_code} {upload_resp.text[:200]}")
            mid = upload_resp.json().get("id")
            if mid:
                media_ids.append(mid)

        print(f"Uploaded {len(media_ids)} images")

        # Post to TikTok via Buffer with all images
        post_resp = requests.post(
            "https://api.bufferapp.com/1/updates/create.json",
            headers={"Authorization": f"Bearer {buffer_token}"},
            json={
                "profile_ids": [buffer_channel],
                "text": f"{caption}\n\n{hashtags}",
                "media": {"photo_ids": media_ids},
                "now": "true"
            }
        )
        print(f"Buffer post: {post_resp.status_code} {post_resp.text[:300]}")

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
