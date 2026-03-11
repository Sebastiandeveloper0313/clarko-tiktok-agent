# render.py — Clarko TikTok Slide Renderer (local photo backgrounds)
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import os, requests, tempfile, textwrap, traceback, json, random, glob

app = Flask(__name__)

WIDTH, HEIGHT = 1080, 1920
PUBLER_TOKEN        = os.environ.get("PUBLER_TOKEN", "")
PUBLER_WORKSPACE_ID = os.environ.get("PUBLER_WORKSPACE_ID", "")
PUBLER_BASE         = "https://app.publer.com/api/v1"

# Background images folder (relative to script)
BG_FOLDER = os.path.join(os.path.dirname(__file__), "backgrounds")

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
    # Smart crop to 9:16 portrait
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
    # Darken for readability
    img = ImageEnhance.Brightness(img).enhance(0.42)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))

    # Semi-transparent center overlay
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

    # Slide counter
    counter = f"{slide_num}/{total}"
    draw.text((WIDTH - 110, 55), counter, fill=(200, 200, 200), font=font_sm)

    # Label
    label = str(slide_data.get("label", "")).upper()
    lb = draw.textbbox((0,0), label, font=font_label)
    lw = lb[2] - lb[0]
    draw.text(((WIDTH - lw) // 2, box_top + 55), label, fill=(180, 160, 255), font=font_label)

    # Thin divider under label
    y = box_top + 115
    draw.line([(WIDTH//2 - 60, y), (WIDTH//2 + 60, y)], fill=(180, 160, 255), width=2)
    y += 30

    # Headline — centered
    headline = str(slide_data.get("headline", ""))
    for line in textwrap.wrap(headline, width=15):
        lb = draw.textbbox((0,0), line, font=font_headline)
        lw = lb[2] - lb[0]
        x = (WIDTH - lw) // 2
        # shadow
        draw.text((x+3, y+3), line, fill=(0,0,0), font=font_headline)
        draw.text((x, y), line, fill=(255, 255, 255), font=font_headline)
        y += 105

    # Divider
    y += 15
    draw.line([(WIDTH//2 - 80, y), (WIDTH//2 + 80, y)], fill=(180, 160, 255), width=2)
    y += 30

    # Subtext — centered
    subtext = str(slide_data.get("subtext", ""))
    if subtext:
        for line in textwrap.wrap(subtext, width=25):
            lb = draw.textbbox((0,0), line, font=font_sub)
            lw = lb[2] - lb[0]
            draw.text(((WIDTH - lw) // 2, y), line, fill=(220, 220, 220), font=font_sub)
            y += 62

    # Branding
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

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
