from flask import Flask, request, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from google.cloud import storage
import json, random, uuid, os, sys, traceback

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# --- ベーシックエンドポイント ---
@app.route("/")
def root():
    return "System Alive ✅"

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

# --- デバッグ用: 環境変数を確認 ---
@app.route("/debug/env")
def debug_env():
    wanted = {k: os.getenv(k) for k in [
        "GCS_BUCKET", "GOOGLE_CLOUD_PROJECT", "K_SERVICE", "K_REVISION", "PORT"
    ]}
    return app.response_class(
        response=json.dumps(wanted, ensure_ascii=False, indent=2),
        status=200,
        mimetype="application/json",
    )

# --- 性格診断フォーム ---
@app.route("/quiz", methods=["GET"])
def quiz():
    return """
<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<title>Horse Mint Demo</title>
<body>
  <h1>性格診断 → 馬トークン発行デモ</h1>
  <form method="post" action="/mint">
    <p>Q1: あなたの気質は？<br>
      <select name="q1">
        <option>冷静沈着</option>
        <option>直感型</option>
        <option>情熱家</option>
      </select>
    </p>
    <p>Q2: チーム or ソロ？<br>
      <select name="q2">
        <option>チーム</option>
        <option>ソロ</option>
      </select>
    </p>
    <p>Q3: 朝型 or 夜型？<br>
      <select name="q3">
        <option>朝型</option>
        <option>夜型</option>
      </select>
    </p>
    <p>Q4: 重視する能力は？<br>
      <select name="q4">
        <option>スピード</option>
        <option>スタミナ</option>
        <option>スキル</option>
      </select>
    </p>
    <p>Q5: 好みのカラーリング<br>
      <input name="q5" placeholder="例: 黒×金">
    </p>
    <button type="submit">診断して発行</button>
  </form>
</body>
</html>
    """

# --- SVG生成ヘルパー ---
def _svg_for(horse):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
  <rect width="100%" height="100%" fill="white"/>
  <text x="32" y="64" font-size="28" font-family="monospace">Horse: {horse["name"]}</text>
  <text x="32" y="110" font-size="20" font-family="monospace">Temp: {horse["temperament"]}</text>
  <text x="32" y="140" font-size="20" font-family="monospace">Team: {horse["teamplay"]}</text>
  <text x="32" y="170" font-size="20" font-family="monospace">Rhythm: {horse["rhythm"]}</text>
  <text x="32" y="200" font-size="20" font-family="monospace">Speed/Stamina/Skill: {horse["speed"]}/{horse["stamina"]}/{horse["skill"]}</text>
  <text x="32" y="230" font-size="20" font-family="monospace">Color: {horse["color"]}</text>
</svg>'''

# --- トークン発行API ---
@app.route("/mint", methods=["POST"])
def mint():
    print("[mint] request received", file=sys.stdout, flush=True)
    data = request.get_json(silent=True) or request.form.to_dict()
    token_id = str(uuid.uuid4())

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

    res = {
        "ok": True,
        "token_id": token_id,
        "horse": horse,
        "permalink": f"{request.url_root}quiz?token={token_id}",
        "asset_url": None,
    }

    bucket_name = os.getenv("GCS_BUCKET")
    print(f"[mint] GCS_BUCKET={bucket_name}", file=sys.stdout, flush=True)

    if bucket_name:
        try:
            svg = _svg_for(horse).encode("utf-8")
            path = f"horses/{token_id}.svg"
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(path)
            blob.upload_from_string(svg, content_type="image/svg+xml")

            res["asset_url"] = f"https://storage.googleapis.com/{bucket_name}/{path}"
            print(f"[mint] uploaded gs://{bucket_name}/{path}", file=sys.stdout, flush=True)
        except Exception as e:
            print("[mint][ERROR] upload failed:", e, file=sys.stdout, flush=True)
            traceback.print_exc()

    if "text/html" in request.headers.get("Accept", "") and not request.is_json:
        return (
            "<pre>" + json.dumps(res, ensure_ascii=False, indent=2) + "</pre>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    return jsonify(res)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
