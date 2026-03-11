# render.py — Clarko TikTok Slide Renderer (Publer API)
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import os, requests, tempfile, textwrap, traceback, base64, json

app = Flask(__name__)

BG_COLOR     = (10, 10, 15)
ACCENT_COLOR = (99, 102, 241)
TEXT_COLOR   = (240, 240, 245)
MUTED_COLOR  = (120, 120, 140)
WIDTH, HEIGHT = 1080, 1920

PUBLER_TOKEN        = os.environ.get("PUBLER_TOKEN", "")
PUBLER_WORKSPACE_ID = os.environ.get("PUBLER_WORKSPACE_ID", "")
PUBLER_BASE         = "https://app.publer.com/api/v1"

def publer_headers():
    return {
        "Authorization": f"Bearer-API {PUBLER_TOKEN}",
        "Publer-Workspace-Id": PUBLER_WORKSPACE_ID,
        "Content-Type": "application/json"
    }

def get_tiktok_account_id():
    resp = requests.get(f"{PUBLER_BASE}/accounts", headers=publer_headers())
    print(f"Accounts response: {resp.status_code} {resp.text[:500]}")
    accounts = resp.json()
    # Find TikTok account
    if isinstance(accounts, list):
        for acc in accounts:
            if acc.get("type", "").lower() == "tiktok" or "tiktok" in acc.get("platform", "").lower():
                return acc["id"]
    elif isinstance(accounts, dict):
        for acc in accounts.get("data", []):
            if acc.get("type", "").lower() == "tiktok" or "tiktok" in acc.get("platform", "").lower():
                return acc["id"]
    raise Exception(f"No TikTok account found in Publer. Response: {resp.text[:300]}")

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

def upload_image_to_publer(png_path):
    with open(png_path, "rb") as f:
        resp = requests.post(
            f"{PUBLER_BASE}/media",
            headers={"Authorization": f"Bearer-API {PUBLER_TOKEN}"},
            files={"file": (os.path.basename(png_path), f, "image/png")},
        )
    print(f"Media upload: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    # Try different response shapes
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

        # 1. Get TikTok account ID
        tiktok_id = get_tiktok_account_id()
        print(f"TikTok account ID: {tiktok_id}")

        # 2. Render + upload each slide
        media_ids = []
        for i, slide in enumerate(slides):
            img      = render_slide(slide, i + 1, len(slides), fonts)
            png_path = os.path.join(tmpdir, f"slide_{i}.png")
            img.save(png_path)
            print(f"Slide {i}: {os.path.getsize(png_path)} bytes")
            mid = upload_image_to_publer(png_path)
            if mid:
                media_ids.append({"id": mid, "type": "image"})
                print(f"Uploaded slide {i} → media id {mid}")
            else:
                print(f"WARNING: No media ID returned for slide {i}")

        print(f"Total media uploaded: {len(media_ids)}")

        # 3. Post to TikTok via Publer
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
        print(f"Posting to Publer: {json.dumps(post_payload)[:500]}")
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
