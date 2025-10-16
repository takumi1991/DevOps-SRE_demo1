from flask import Flask, request, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import os, json, random, uuid, base64

# Google Cloud
from google.cloud import storage

# Gemini (google-genai >= 0.3.0)
try:
    from google import genai
except Exception:
    genai = None  # ライブラリが無い場合でもサーバは起動できるように

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ---------------- 基本ヘルス ----------------
@app.route("/")
def root():
    return "✅ System Alive ✅ (build: v20251016-22:54)"

@app.route("/health")
def health():
    return "ok", 200

@app.route("/error")
def error():
    return "intentional error", 500

@app.route("/metrics")
def metrics():
    latency = random.random()
    text = (
        "# HELP response_latency_seconds Demo latency\n"
        "# TYPE response_latency_seconds gauge\n"
        f"response_latency_seconds {latency}\n"
    )
    return Response(text, mimetype="text/plain; version=0.0.4")

# ---------------- デバッグ（今の環境変数） ----------------
@app.route("/debug/env", methods=["GET"])
def debug_env():
    masked = {}
    for k, v in os.environ.items():
        masked[k] = "***" if any(s in k for s in ["KEY","SECRET","TOKEN","PASSWORD"]) else v
    return jsonify({"env": masked})

# ---------------- フォーム（性格診断） ----------------
@app.route("/quiz", methods=["GET"])
def quiz():
    return """
<!doctype html><html lang="ja"><meta charset="utf-8"><title>Horse Mint Demo</title>
<body>
  <h1>性格診断 → 馬トークン発行（Gemini画像生成版）</h1>
  <form method="post" action="/mint">
    <p>Q1: あなたの気質は？<br>
      <select name="q1"><option>冷静沈着</option><option>直感型</option><option>情熱家</option></select>
    </p>
    <p>Q2: チーム or ソロ？<br>
      <select name="q2"><option>チーム</option><option>ソロ</option></select>
    </p>
    <p>Q3: 朝型 or 夜型？<br>
      <select name="q3"><option>朝型</option><option>夜型</option></select>
    </p>
    <p>Q4: 重視する能力は？<br>
      <select name="q4"><option>スピード</option><option>スタミナ</option><option>スキル</option></select>
    </p>
    <p>Q5: 好みのカラーリング（例: 黒×金）<br>
      <input name="q5" placeholder="例: 黒×金">
    </p>
    <button type="submit">診断して発行</button>
  </form>
</body></html>
    """

# ---------------- ミント（発行）API ----------------
@app.route("/mint", methods=["POST"])
def mint():
    data = request.get_json(silent=True) or request.form.to_dict()
    token_id = str(uuid.uuid4())

    # 簡易ロジックで能力値
    base = {"スピード": 7, "スタミナ": 6, "スキル": 6}
    key = (data.get("q4") or "").strip()
    if key in base:
        base[key] = 9

    horse = {
        "name": "Starter Horse",
        "temperament": data.get("q1", "Balanced"),
        "teamplay": data.get("q2", "チーム"),
        "rhythm": data.get("q3", "朝型"),
        "color": data.get("q5", "紫×金"),
        "speed": base["スピード"],
        "stamina": base["スタミナ"],
        "skill": base["スキル"],
        "catchphrase": "Ride on!",
    }

    bucket_name = os.getenv("GCS_BUCKET")
    use_gemini = True  # 常にGeminiを試す（失敗時はSVGにフォールバック）

    asset_url = None
    if bucket_name:
        # 1) まず Gemini で PNG 画像生成を試す
        if use_gemini:
            try:
                png_bytes = _gen_horse_with_gemini(horse)
                if png_bytes:
                    path = f"horses/{token_id}.png"
                    _upload_bytes_to_gcs(bucket_name, path, png_bytes, "image/png")
                    asset_url = f"https://storage.googleapis.com/{bucket_name}/{path}"
                    print(f"[Gemini] image uploaded -> {asset_url}")
            except Exception as e:
                print(f"[Gemini][ERROR] {e}")

        # 2) Gemini が失敗したら、SVG 馬シルエットを保存
        if not asset_url:
            try:
                svg = _svg_for(horse).encode("utf-8")
                path = f"horses/{token_id}.svg"
                _upload_bytes_to_gcs(bucket_name, path, svg, "image/svg+xml")
                asset_url = f"https://storage.googleapis.com/{bucket_name}/{path}"
                print(f"[SVG] fallback uploaded -> {asset_url}")
            except Exception as e:
                print(f"[SVG][ERROR] {e}")
    else:
        print("[GCS] GCS_BUCKET not set; skip upload")

    res = {
        "ok": True,
        "token_id": token_id,
        "horse": horse,
        "permalink": f"{request.url_root}quiz?token={token_id}",
        "asset_url": asset_url,
        "generator": "gemini" if (asset_url and asset_url.endswith(".png")) else "svg-fallback"
    }

    # フォームから来た時は見やすくHTMLでも返せる
    if "text/html" in request.headers.get("Accept", "") and not request.is_json:
        return (
            "<pre>" + json.dumps(res, ensure_ascii=False, indent=2) + "</pre>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    return jsonify(res)

# ---------- Gemini 画像生成 ----------
def _gen_horse_with_gemini(horse: dict) -> bytes | None:
    """
    Gemini の画像生成APIで馬のPNGを作る。
    - google-genai>=0.3.0 を想定
    - モデル名は 'imagen-3.0-generate'（現行の画像モデル）を利用
    失敗時は None を返す。
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not genai:
        print("[Gemini] client unavailable")
        return None

    prompt = (
        "A stylized race horse full-body, dynamic pose, clean white background. "
        f"Primary color theme: {horse['color']}. "
        f"Personality: {horse['temperament']}. "
        f"Playstyle: {horse['teamplay']}, Rhythm: {horse['rhythm']}. "
        "Crisp 2D illustration, high contrast, no text overlay."
    )

    client = genai.Client(api_key=api_key)

    # 画像サイズはコストと速度の妥協で 768 を採用（必要なら 1024 など）
    resp = client.images.generate(
        model="imagen-3.0-generate",
        prompt=prompt,
        size="768x768"
    )

    # 念のためいくつかのフィールド名に対応
    try:
        data0 = resp.data[0]
    except Exception:
        data0 = None

    if not data0:
        return None

    # 代表的な返却形状に対応
    if hasattr(data0, "b64_json") and data0.b64_json:
        return base64.b64decode(data0.b64_json)
    if getattr(data0, "image", None):
        # SDK によっては bytes がそのまま入る
        return data0.image
    if getattr(data0, "content", None):
        return data0.content  # bytes

    # 他の形の場合は諦める
    return None

# ---------- GCS ユーティリティ ----------
def _upload_bytes_to_gcs(bucket: str, path: str, content: bytes, content_type: str):
    client = storage.Client()
    b = client.bucket(bucket)
    blob = b.blob(path)
    blob.upload_from_string(content, content_type=content_type)

# ---------- フォールバック SVG（馬シルエット） ----------
def _svg_for(horse: dict) -> str:
    body_color = "#654321"
    accent = "#000000"
    text_color = "#222222"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
  <!-- v2-silhouette -->
  <rect width="100%" height="100%" fill="white"/>
  <ellipse cx="320" cy="200" rx="120" ry="60" fill="{body_color}" />
  <rect x="410" y="120" width="30" height="60" fill="{body_color}" />
  <circle cx="440" cy="120" r="20" fill="{body_color}" />
  <rect x="260" y="250" width="15" height="70" fill="{accent}" />
  <rect x="300" y="250" width="15" height="70" fill="{accent}" />
  <rect x="360" y="250" width="15" height="70" fill="{accent}" />
  <rect x="400" y="250" width="15" height="70" fill="{accent}" />
  <path d="M 200 200 Q 180 240 220 220" stroke="{accent}" stroke-width="10" fill="none"/>
  <text x="32" y="40" font-size="22" fill="{text_color}" font-family="monospace">
    {horse["name"]} ({horse["color"]})
  </text>
  <text x="32" y="70" font-size="16" fill="{text_color}" font-family="monospace">
    {horse["temperament"]} / {horse["teamplay"]} / {horse["rhythm"]}
  </text>
  <text x="32" y="95" font-size="16" fill="{text_color}" font-family="monospace">
    Speed:{horse["speed"]}  Sta:{horse["stamina"]}  Skill:{horse["skill"]}
  </text>
</svg>'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
# trigger test
# trigger again
