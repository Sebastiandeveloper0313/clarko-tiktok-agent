# render.py — Clarko TikTok Slide Renderer (local photo backgrounds)
from flask import Flask, request, jsonify, Response
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import os, requests, tempfile, textwrap, traceback, json, random, glob, io, base64

app = Flask(__name__)

WIDTH, HEIGHT = 1080, 1920
PUBLER_TOKEN        = os.environ.get("PUBLER_TOKEN", "")
PUBLER_WORKSPACE_ID = os.environ.get("PUBLER_WORKSPACE_ID", "")
PUBLER_BASE         = "https://app.publer.com/api/v1"

# Background images folder (relative to script)
BG_FOLDER = os.path.join(os.path.dirname(__file__), "backgrounds")

# In-memory store for last preview
_last_preview_html = None

def publer_headers():
    return {
        "Authorization": f"Bearer-API {PUBLER_TOKEN}",
        "Publer-Workspace-Id": PUBLER_WORKSPACE_ID,
        "Content-Type": "application/json"
    }

def get_tiktok_account_id():
    resp = requests.get(f"{PUBLER_BASE}/accounts", headers=publer_headers())
    print(f"Accounts: {resp.status_code} {resp.text[:300]}")
    accounts = resp.json()
    if isinstance(accounts, list):
        for acc in accounts:
            if "tiktok" in str(acc.get("type", "")).lower() or "tiktok" in str(acc.get("platform", "")).lower():
                return acc["id"]
    elif isinstance(accounts, dict):
        for acc in accounts.get("data", []):
            if "tiktok" in str(acc.get("type", "")).lower() or "tiktok" in str(acc.get("platform", "")).lower():
                return acc["id"]
    raise Exception(f"No TikTok account found. Response: {resp.text[:300]}")

def get_background_photo():
    patterns = [
        os.path.join(BG_FOLDER, "*.jpg"),
        os.path.join(BG_FOLDER, "*.jpeg"),
        os.path.join(BG_FOLDER, "*.png"),
        os.path.join(BG_FOLDER, "*.webp"),
    ]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    if not files:
        print("No background images found, using gradient")
        img = Image.new("RGB", (WIDTH, HEIGHT), (20, 20, 25))
        return img
    chosen = random.choice(files)
    print(f"Using background: {chosen}")
    img = Image.open(chosen).convert("RGB")
    iw, ih = img.size
    target_ratio = WIDTH / HEIGHT
    current_ratio = iw / ih
    if current_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        left = (iw - new_w) // 2
        img = img.crop((left, 0, left + new_w, ih))
    else:
        new_h = int(iw / target_ratio)
        top = (ih - new_h) // 2
        img = img.crop((0, top, iw, top + new_h))
    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    return img

def get_fonts():
    try:
        return (
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 82),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34),
        )
    except Exception as e:
        print(f"Font load failed: {e}")
        d = ImageFont.load_default()
        return d, d, d, d

def render_slide(slide_data, slide_num, total, fonts, bg_img):
    font_headline, font_sub, font_label, font_sm = fonts

    img = bg_img.copy()
    img = ImageEnhance.Brightness(img).enhance(0.42)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    box_top    = HEIGHT // 2 - 440
    box_bottom = HEIGHT // 2 + 440
    ov_draw.rounded_rectangle(
        [(80, box_top), (WIDTH - 80, box_bottom)],
        radius=24,
        fill=(0, 0, 0, 150)
    )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    counter = f"{slide_num}/{total}"
    draw.text((WIDTH - 110, 55), counter, fill=(200, 200, 200), font=font_sm)

    label = str(slide_data.get("label", "")).upper()
    if label and label != "HOOK":
        lb = draw.textbbox((0,0), label, font=font_label)
        lw = lb[2] - lb[0]
        draw.text(((WIDTH - lw) // 2, box_top + 55), label, fill=(180, 160, 255), font=font_label)

    y = box_top + 115
    draw.line([(WIDTH//2 - 60, y), (WIDTH//2 + 60, y)], fill=(180, 160, 255), width=2)
    y += 30

    headline = str(slide_data.get("headline", "")).replace("—", "-").replace("–", "-")
    for line in textwrap.wrap(headline, width=15):
        lb = draw.textbbox((0,0), line, font=font_headline)
        lw = lb[2] - lb[0]
        x = (WIDTH - lw) // 2
        draw.text((x+3, y+3), line, fill=(0,0,0), font=font_headline)
        draw.text((x, y), line, fill=(255, 255, 255), font=font_headline)
        y += 105

    y += 15
    draw.line([(WIDTH//2 - 80, y), (WIDTH//2 + 80, y)], fill=(180, 160, 255), width=2)
    y += 30

    subtext = str(slide_data.get("subtext", "")).replace("—", "-").replace("–", "-")
    if subtext:
        for line in textwrap.wrap(subtext, width=25):
            lb = draw.textbbox((0,0), line, font=font_sub)
            lw = lb[2] - lb[0]
            draw.text(((WIDTH - lw) // 2, y), line, fill=(220, 220, 220), font=font_sub)
            y += 62

    brand = "clarko.ai"
    lb = draw.textbbox((0,0), brand, font=font_label)
    bw = lb[2] - lb[0]
    draw.text(((WIDTH - bw) // 2, HEIGHT - 90), brand, fill=(180, 160, 255), font=font_label)

    return img.convert("RGB")

def upload_image_to_publer(png_path):
    with open(png_path, "rb") as f:
        resp = requests.post(
            f"{PUBLER_BASE}/media",
            headers={
                "Authorization": f"Bearer-API {PUBLER_TOKEN}",
                "Publer-Workspace-Id": PUBLER_WORKSPACE_ID,
            },
            files={"file": (os.path.basename(png_path), f, "image/png")},
        )
    print(f"Media upload: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    if isinstance(data, dict):
        return data.get("id") or data.get("data", {}).get("id")
    return None

def build_slides_html(slides, caption=""):
    fonts  = get_fonts()
    bg_img = get_background_photo()
    images_html = ""
    for i, slide in enumerate(slides):
        img = render_slide(slide, i + 1, len(slides), fonts, bg_img)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        images_html += f"""
        <div style="display:flex;flex-direction:column;align-items:center;gap:8px">
            <span style="color:#aaa;font-size:13px">Slide {i+1}</span>
            <img src="data:image/jpeg;base64,{b64}"
                 style="height:500px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.5)"/>
        </div>"""

    caption_html = ""
    if caption:
        caption_html = f"""
        <div style="max-width:700px;margin:30px auto 0;background:#1e1e2e;border-radius:12px;padding:20px">
            <p style="color:#bbb;font-size:13px;margin:0 0 8px">Caption</p>
            <p style="color:#fff;font-size:15px;white-space:pre-wrap;margin:0">{caption}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Clarko TikTok Preview</title>
  <style>
    body {{ margin:0; background:#0d0d1a; font-family:sans-serif; }}
    h1 {{ text-align:center; color:#b4a0ff; padding:30px 0 10px; margin:0; font-size:22px; }}
    .slides {{ display:flex; gap:20px; overflow-x:auto; padding:20px 30px 30px; }}
  </style>
</head>
<body>
  <h1>🎬 Clarko TikTok Preview</h1>
  <div class="slides">{images_html}</div>
  {caption_html}
</body>
</html>"""

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

        fonts  = get_fonts()
        tmpdir = tempfile.mkdtemp()
        bg_img = get_background_photo()

        tiktok_id = get_tiktok_account_id()
        print(f"TikTok ID: {tiktok_id}")

        media_ids = []
        for i, slide in enumerate(slides):
            img      = render_slide(slide, i + 1, len(slides), fonts, bg_img)
            png_path = os.path.join(tmpdir, f"slide_{i}.png")
            img.save(png_path)
            print(f"Slide {i}: {os.path.getsize(png_path)} bytes")
            mid = upload_image_to_publer(png_path)
            if mid:
                media_ids.append({"id": mid, "type": "image"})
                print(f"Slide {i} → {mid}")
            else:
                print(f"WARNING: no ID for slide {i}")

        print(f"Total uploaded: {len(media_ids)}")

        post_payload = {
            "bulk": {
                "state": "published",
                "posts": [{
                    "networks": {
                        "tiktok": {
                            "type": "photo",
                            "text": f"{caption}\n\n{hashtags}",
                            "media": media_ids
                        }
                    },
                    "accounts": [{"id": tiktok_id}]
                }]
            }
        }
        post_resp = requests.post(
            f"{PUBLER_BASE}/posts/schedule/publish",
            headers=publer_headers(),
            json=post_payload
        )
        print(f"Publer post: {post_resp.status_code} {post_resp.text[:500]}")
        return jsonify({"ok": True, "publer": post_resp.json()})

    except Exception as e:
        tb = traceback.format_exc()
        print(f"ERROR: {tb}")
        return jsonify({"ok": False, "error": str(e), "traceback": tb}), 500


@app.route("/preview", methods=["POST"])
def preview_endpoint():
    """Called by n8n — renders slides and saves HTML, returns a link to view it."""
    global _last_preview_html
    try:
        data   = request.get_json(force=True)
        slides = data.get("slides", [])
        caption = data.get("caption", "")
        if not slides:
            return jsonify({"ok": False, "error": "No slides"}), 400

        _last_preview_html = build_slides_html(slides, caption)

        # Return the preview URL so n8n can show it
        host = request.host_url.rstrip("/")
        preview_url = f"{host}/preview-page"
        return jsonify({"ok": True, "preview_url": preview_url})

    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"ok": False, "error": str(e), "traceback": tb}), 500


@app.route("/preview-page", methods=["GET"])
def preview_page():
    """Open this URL in your browser to see the last preview."""
    global _last_preview_html
    if not _last_preview_html:
        return Response(
            "<html><body style='background:#0d0d1a;color:#fff;font-family:sans-serif;text-align:center;padding:60px'>"
            "<h2>No preview yet</h2><p>Run your n8n workflow with /preview first.</p></body></html>",
            mimetype="text/html"
        )
    return Response(_last_preview_html, mimetype="text/html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
