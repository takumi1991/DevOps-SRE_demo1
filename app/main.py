from flask import Flask, request, jsonify, Response, make_response
import os, time, uuid, json, base64

from google.cloud import storage
from google import genai  # pip install google-genai

# ──────────────────────────────────────────────────────────────────────────────
# App / Clients
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

# 必須: Cloud Run の「変数とシークレット」で設定
BUCKET = os.environ["GCS_BUCKET"]  # 例: devops-sre-demo1-horse-assets

# Gemini クライアント（環境変数 GEMINI_API_KEY を自動検出）
client = genai.Client()

# GCS クライアント
gcs = storage.Client()
bucket = gcs.bucket(BUCKET)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def upload_bytes(path: str, data: bytes, content_type: str, public: bool = True) -> str:
    """GCS にデータをアップロードして公開URLを返す（デモ向け: 公開）"""
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    if public:
        blob.make_public()
    return blob.public_url

def upload_json(path: str, obj: dict, public: bool = True) -> str:
    return upload_bytes(path, json.dumps(obj, ensure_ascii=False).encode(), "application/json", public)

def gen_text(persona: str, stats: dict) -> str:
    """Gemini でフレーバーテキスト（1文）を生成"""
    prompt = (
        "Write ONE short, uplifting sentence (max ~20 words) describing a race horse NFT.\n"
        f"Persona: {persona}\n"
        f"Stats: {stats}\n"
        "Return only the sentence."
    )
    r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return (getattr(r, "text", "") or "").strip()

def gen_image_gemini(prompt: str) -> bytes:
    """
    Gemini Images API で画像生成（base64→bytes）
    モデル: imagen-3.0-generate-001
    SDKのレスポンスが環境で差異あるため、代表的な取り出しパスを順に試す。
    """
    result = client.models.generate_images(
        model="imagen-3.0-generate-001",
        prompt=prompt,
    )

    # 代表的なレスポンスの取り出しパターン
    img_bytes = None
    if hasattr(result, "generated_images") and result.generated_images:
        gi = result.generated_images[0]
        # A) generated_images[0].data が base64
        if hasattr(gi, "data") and gi.data:
            img_bytes = base64.b64decode(gi.data)
        # B) generated_images[0].image.inline_data.data が base64
        elif hasattr(gi, "image") and getattr(gi.image, "inline_data", None):
            b64 = gi.image.inline_data.data
            if b64:
                img_bytes = base64.b64decode(b64)

    if not img_bytes:
        raise RuntimeError("Gemini image generation: no image data in response")

    return img_bytes

# ──────────────────────────────────────────────────────────────────────────────
# Basic endpoints
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return "System Alive ✅"

@app.get("/health")
def health():
    return ("ok", 200)

@app.get("/metrics")
def metrics():
    # 必要ならメトリクスを拡張（ここでは固定の情報系メトリクス）
    text = "# HELP app_info Info metric\n# TYPE app_info gauge\napp_info{service=\"horse-demo\"} 1\n"
    return Response(text, mimetype="text/plain; version=0.0.4")

# ──────────────────────────────────────────────────────────────────────────────
# CORS（必要な場合のみ。デモでは緩めに全許可）
# ──────────────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

@app.route("/mint", methods=["OPTIONS"])
def mint_options():
    return ("", 204)

# ──────────────────────────────────────────────────────────────────────────────
# Quiz UI（性格診断 → /mint に POST）
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/quiz")
def quiz():
    html = """<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Horse Personality Mint</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto;margin:24px;max-width:720px}
  .card{border:1px solid #eee;border-radius:16px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
  button{padding:10px 16px;border-radius:10px;border:0;background:#2563eb;color:#fff;cursor:pointer}
  button:disabled{opacity:.6;cursor:not-allowed}
  .muted{color:#666}
  .row{margin:12px 0}
  input[type=range]{width:100%}
  .result{margin-top:20px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
</style>
</head><body>
  <h1>性格診断 → 馬トークン生成（Gemini 画像＋テキスト）</h1>
  <p class="muted">各質問を1〜5で回答してください（1: いいえ / 5: とても当てはまる）。</p>

  <div class="card">
    <div class="row"><b>Q1.</b> 新しい環境でもすぐに馴染めるほうだ</div>
    <input id="q1" type="range" min="1" max="5" value="3" oninput="v1.textContent=this.value"><span id="v1">3</span>

    <div class="row"><b>Q2.</b> 長時間コツコツ続けるのが得意だ</div>
    <input id="q2" type="range" min="1" max="5" value="3" oninput="v2.textContent=this.value"><span id="v2">3</span>

    <div class="row"><b>Q3.</b> 困難な状況でも落ち着いて対処できる</div>
    <input id="q3" type="range" min="1" max="5" value="3" oninput="v3.textContent=this.value"><span id="v3">3</span>

    <div class="row"><b>Q4.</b> チームワークを大切にしている</div>
    <input id="q4" type="range" min="1" max="5" value="3" oninput="v4.textContent=this.value"><span id="v4">3</span>

    <div class="row"><b>Q5.</b> スピード重視で動くことが多い</div>
    <input id="q5" type="range" min="1" max="5" value="3" oninput="v5.textContent=this.value"><span id="v5">3</span>

    <div class="row">
      <label for="hint"><b>生成ヒント（任意）</b></label>
      <input id="hint" placeholder="neon cyberpunk, Tokyo night, etc." style="width:100%;padding:10px;border:1px solid #ddd;border-radius:10px"/>
    </div>

    <div class="grid">
      <button id="run" onclick="mint()">診断して発行する</button>
      <button id="openMy" onclick="openMy()">My Horses を開く</button>
    </div>

    <div id="out" class="result muted"></div>
  </div>

  <h2 style="margin-top:32px">My Horses（この端末に保存）</h2>
  <div id="list" class="grid"></div>

<script>
const KEY = "my_horses";

function getAns(){ return [
  +document.getElementById('q1').value,
  +document.getElementById('q2').value,
  +document.getElementById('q3').value,
  +document.getElementById('q4').value,
  +document.getElementById('q5').value,
];}

async function mint(){
  const btn = document.getElementById('run');
  const out = document.getElementById('out');
  btn.disabled = true; out.textContent = "生成中…（30秒前後かかる場合があります）";

  try {
    const res = await fetch('/mint', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({answers: getAns(), user_hint: document.getElementById('hint').value || ""})
    });
    if(!res.ok){ throw new Error('failed: ' + res.status); }
    const data = await res.json();

    // localStorage に保存
    const list = JSON.parse(localStorage.getItem(KEY) || "[]");
    list.push({
      token_id: data.token_id,
      name: data.name,
      image: data.image_url,
      permalink: data.permalink
    });
    localStorage.setItem(KEY, JSON.stringify(list));

    out.innerHTML = '✅ 発行完了: <a href="'+data.permalink+'" target="_blank">カードを開く</a>';
    renderList();
  } catch(e){
    out.textContent = 'エラー: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

function renderList(){
  const list = JSON.parse(localStorage.getItem(KEY) || "[]").slice().reverse();
  const el = document.getElementById('list');
  el.innerHTML = "";
  list.forEach(h => {
    const div = document.createElement('div');
    div.className = "card";
    div.innerHTML = `
      <img src="${h.image}" style="width:100%;border-radius:12px;margin-bottom:8px"/>
      <div><b>${h.name || 'Unnamed'}</b></div>
      <a href="${h.permalink}" target="_blank">Open</a>
    `;
    el.appendChild(div);
  });
}

function openMy(){
  // 同ページ下部に一覧を表示しているのでスクロール
  document.getElementById('list').scrollIntoView({behavior:'smooth'});
}

renderList();
</script>
</body></html>"""
    return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})

# ──────────────────────────────────────────────────────────────────────────────
# Main: /mint
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/mint")
def mint():
    """
    Body 例:
    {
      "answers": [1,2,3,4,5],
      "user_hint": "neon cyberpunk"
    }
    """
    try:
        body = request.get_json(silent=True) or {}
        answers = body.get("answers", [])
        user_hint = (body.get("user_hint") or "").strip()

        # 簡易スコアから性格/能力にマッピング
        total = sum([int(x) for x in answers]) if answers else 15
        persona = "confident" if total >= 15 else "calm"
        stats = {
            "Speed":  60 + (total % 41),
            "Stamina":55 + ((answers[0] if answers else 10) % 46),
            "Loyalty":50 + ((answers[1] if answers else 10) % 51),
        }

        # テキスト（Gemini）
        flavor = gen_text(persona, stats)

        # 画像（Gemini Images）
        img_prompt = f"A {persona} futuristic race horse portrait, 3D, high detail, trending art. {user_hint}"
        img_bytes = gen_image_gemini(img_prompt)

        # 永続化（GCS）
        token_id = str(uuid.uuid4())
        base_path = f"tokens/{token_id}"
        image_url = upload_bytes(f"{base_path}/image.png", img_bytes, "image/png")

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
            "token_id": token_id,
            "model": {"text": "gemini-2.5-flash", "image": "imagen-3.0-generate-001"}
        }
        meta_url = upload_json(f"{base_path}/metadata.json", metadata)

        # シンプルなカードHTML（パーマリンク）
        html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{metadata["name"]}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>body{{font-family:system-ui,-apple-system,Segoe UI,Roboto;max-width:720px;margin:24px}}
  img{{max-width:100%;border-radius:12px}}</style></head>
<body>
  <h1>{metadata["name"]}</h1>
  <img src="{image_url}" alt="horse"/>
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

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint (for local run)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Cloud Run は PORT 環境変数を使う
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
