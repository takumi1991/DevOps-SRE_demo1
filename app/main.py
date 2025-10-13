from flask import Flask, request, jsonify
import os, time, uuid, json, base64, requests
from google.cloud import storage
from google import genai

app = Flask(__name__)
BUCKET = os.environ["GCS_BUCKET"]
gcs = storage.Client()
bucket = gcs.bucket(BUCKET)
client = genai.Client()  # GEMINI_API_KEY を自動検出

CRAIYON_API = "https://api.craiyon.com/v3"

def upload_bytes(path, data, content_type, public=True):
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    if public:
        blob.make_public()
    return blob.public_url

def upload_json(path, obj, public=True):
    return upload_bytes(path, json.dumps(obj, ensure_ascii=False).encode(), "application/json", public)

def gen_text(persona, stats):
    prompt = (
        f"One-sentence flavor text for a race horse.\n"
        f"Persona: {persona}\n"
        f"Stats: {stats}\n"
        f"Tone: concise, uplifting."
    )
    r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return (r.text or "").strip()

def gen_image_craiyon(prompt, tries=2, timeout=60):
    for _ in range(tries):
        res = requests.post(CRAIYON_API, json={"prompt": prompt}, timeout=timeout)
        if res.ok:
            b64 = res.json().get("images", [None])[0]
            if b64:
                return base64.b64decode(b64)
        time.sleep(2)
    raise RuntimeError("Craiyon generation failed")

@app.post("/mint")
def mint():
    body = request.get_json(silent=True) or {}
    answers = body.get("answers", [])
    user_hint = body.get("user_hint", "")

    persona = "confident" if sum(map(int, answers or [5])) >= 15 else "calm"
    stats = {
        "Speed":  60 + (sum(answers or [0]) % 41),
        "Stamina":55 + ((answers[0] if answers else 10) % 46),
        "Loyalty":50 + ((answers[1] if answers else 10) % 51),
    }
    flavor = gen_text(persona, stats)

    img = gen_image_craiyon(
        f"a {persona} futuristic race horse portrait, high detail, 3d render, {user_hint}"
    )

    token_id = str(uuid.uuid4())
    base_path = f"tokens/{token_id}"
    image_url = upload_bytes(f"{base_path}/image.png", img, "image/png")

    metadata = {
        "name": f"{persona.title()} Runner",
        "description": flavor,
        "image": image_url,
        "attributes": [
            {"trait_type": "Speed", "value": stats["Speed"]},
            {"trait_type": "Stamina", "value": stats["Stamina"]},
            {"trait_type": "Loyalty", "value": stats["Loyalty"]},
        ],
        "created_at": int(time.time()),
        "token_id": token_id
    }
    meta_url = upload_json(f"{base_path}/metadata.json", metadata)

    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{metadata["name"]}</title></head>
<body style="font-family:sans-serif;margin:20px;max-width:680px">
  <h1>{metadata["name"]}</h1>
  <img src="{image_url}" alt="horse" style="max-width:512px;width:100%;border-radius:8px"/>
  <p>{flavor}</p>
  <ul>
    <li>Speed: {stats["Speed"]}</li>
    <li>Stamina: {stats["Stamina"]}</li>
    <li>Loyalty: {stats["Loyalty"]}</li>
  </ul>
  <p>Token ID: {token_id}</p>
  <p><a href="{meta_url}" target="_blank">metadata.json</a></p>
</body></html>"""
    permalink = upload_bytes(f"{base_path}/index.html", html.encode(), "text/html")

    return jsonify({
        "token_id": token_id,
        "name": metadata["name"],
        "image_url": image_url,
        "metadata_url": meta_url,
        "permalink": permalink
    }), 201

@app.get("/health")
def health(): return ("ok", 200)
