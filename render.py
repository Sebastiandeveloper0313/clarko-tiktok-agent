# render.py — Clarko TikTok Slide Renderer
from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import os, json, subprocess, requests, tempfile, textwrap

app = Flask(__name__)

# ── Config ──────────────────────────────────────────────
BG_COLOR     = (10, 10, 15)        # dark background
ACCENT_COLOR = (99, 102, 241)      # indigo — change to your brand color
TEXT_COLOR   = (240, 240, 245)
MUTED_COLOR  = (120, 120, 140)
WIDTH, HEIGHT = 1080, 1920         # TikTok portrait dimensions

def render_slide(slide_data, slide_num, total):
    img    = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw   = ImageDraw.Draw(img)

    # Load fonts (fallback to default if custom not present)
    try:
        font_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        font_med  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 44)
        font_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except:
        font_big = font_med = font_sm = ImageFont.load_default()

    # Accent top bar
    draw.rectangle([(0, 0), (WIDTH, 8)], fill=ACCENT_COLOR)

    # Slide counter (top right)
    counter_text = f"{slide_num}/{total}"
    draw.text((WIDTH - 80, 30), counter_text, fill=MUTED_COLOR, font=font_sm)

    # Label (e.g. "HOOK", "TIP 1", "CTA")
    label = slide_data.get("label", "").upper()
    draw.text((60, 120), label, fill=ACCENT_COLOR, font=font_sm)

    # Main headline — wrapped
    headline = slide_data.get("headline", "")
    lines    = textwrap.wrap(headline, width=20)
    y_pos    = 220
    for line in lines:
        draw.text((60, y_pos), line, fill=TEXT_COLOR, font=font_big)
        y_pos += 90

    # Subtext
    subtext = slide_data.get("subtext", "")
    if subtext:
        sub_lines = textwrap.wrap(subtext, width=30)
        y_pos += 30
        for line in sub_lines:
            draw.text((60, y_pos), line, fill=MUTED_COLOR, font=font_med)
            y_pos += 56

    # Bottom branding
    draw.rectangle([(0, HEIGHT-90), (WIDTH, HEIGHT)], fill=(18,18,24))
    draw.text((60, HEIGHT-65), "clarko.ai", fill=MUTED_COLOR, font=font_sm)

    return img


def make_video(slides_data, output_path):
    tmpdir = tempfile.mkdtemp()
    total  = len(slides_data)

    # Render each slide as PNG
    for i, slide in enumerate(slides_data):
        img = render_slide(slide, i+1, total)
        img.save(os.path.join(tmpdir, f"slide_{i:03d}.png"))

    # Build file list for ffmpeg (no glob needed)
    list_file = os.path.join(tmpdir, "files.txt")
    with open(list_file, "w") as f:
        for i in range(total):
            slide_path = os.path.join(tmpdir, f"slide_{i:03d}.png")
            f.write(f"file '{slide_path}'\n")
            f.write(f"duration 3\n")

    # Use ffmpeg concat demuxer instead of glob
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-vf", "fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        output_path
    ], check=True)

    return output_path

@app.route("/render", methods=["POST"])
def render_endpoint():
    try:
        data       = request.get_json()
        slides     = data["slides"]          # list of {label, headline, subtext}
        caption    = data.get("caption", "")
        hashtags   = data.get("hashtags", "")

        out_path   = f"/tmp/tiktok_{os.urandom(4).hex()}.mp4"
        make_video(slides, out_path)

        # Upload to Buffer
        buffer_token   = os.environ["BUFFER_TOKEN"]
        buffer_channel = os.environ["BUFFER_CHANNEL_ID"]

        with open(out_path, "rb") as f:
            upload = requests.post(
                "https://api.bufferapp.com/1/media/upload.json",
                headers={"Authorization": f"Bearer {buffer_token}"},
                files={"file": ("tiktok.mp4", f, "video/mp4")},
            )
        media_id = upload.json().get("id")

        # Schedule post via Buffer
        post_text = f"{caption}\n\n{hashtags}"
        response  = requests.post(
            "https://api.bufferapp.com/1/updates/create.json",
            headers={"Authorization": f"Bearer {buffer_token}"},
            json={
                "profile_ids": [buffer_channel],
                "text": post_text,
                "media": {"video_id": media_id},
                "now": "true"
            }
        )

        os.remove(out_path)
        return jsonify({"ok": True, "buffer": response.json()})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
