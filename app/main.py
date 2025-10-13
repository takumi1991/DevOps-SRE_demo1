from flask import Flask, request, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import os, json, random, uuid
from google.cloud import storage

app = Flask(__name__)
# Cloud Run のプロキシヘッダを信頼
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ---------- 画像(SVG)を生成するヘルパ ----------
def _svg_for(horse: dict) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
  <rect width="100%" height="100%" fill="white"/>
  <text x="32" y="64" font-size="28" font-family="monospace">Horse: {horse["name"]}</text>
  <text x="32" y="110" font-size="20" font-family="monospace">Temp: {horse["temperament"]}</text>
  <text x="32" y="140" font-size="20" font-family="monospace">Team: {horse["teamplay"]}</text>
  <text x="32" y="170" font-size="20" font-family="monospace">Rhythm: {horse["rhythm"]}</text>
  <text x="32" y="200" font-size="20" font-family="monospace">Speed/Stamina/Skill: {horse["speed"]}/{horse["stamina"]}/{horse["skill"]}</text>
  <text x="32" y="230" font-size="20" font-family="monospace">Color: {horse["color"]}</text>
</svg>'''

# ---------- 既存の簡易エンドポイント ----------
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

# ---------- 性格診断フォーム ----------
@app.route("/quiz", methods=["GET"])
def quiz():
    return """
<!doctype html>
<html lang="ja"><meta charset="utf-8"><title>Horse Mint Demo</title>
<body>
  <h1>性格診断 → 馬トークン発行デモ</h1>
  <form method="post" action="/mint">
    <p>Q1: あなたの気質は？<br>
      <select name="q1">
        <option>冷静沈着</option><option>直感型</option><option>情熱家</option>
      </select>
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
    <p>Q5: 好みのカラーリング<br><input name="q5" placeholder="例: 黒×金"></p>
    <button type="submit">診断して発行</button>
  </form>
</body></html>
    """

# ---------- 発行API（GCSへSVG保存） ----------
@app.route("/mint", methods=["POST"])
def mint():
    data = request.get_json(silent=True) or request.form.to_dict()
    token_id = str(uuid.uuid4())

    # 能力値をざっくり決める
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

    # GCS 保存
    bucket_name = os.getenv("GCS_BUCKET")
    if bucket_name:
        try:
            svg = _svg_for(horse).encode("utf-8")
            path = f"horses/{token_id}.svg"
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(path)
            blob.upload_from_string(svg, content_type="image/svg+xml")
            # 公開バケットならこのURLで閲覧可能
            res["asset_url"] = f"https://storage.googleapis.com/{bucket_name}/{path}"
        except Exception as e:
            # 失敗しても Mint 自体は返す（ログに理由を出す）
            print(f"[mint] GCS upload failed: {e}")

    # HTML で見やすく返す（フォームPOST向け）
    if "text/html" in request.headers.get("Accept", "") and not request.is_json:
        return (
            "<pre>" + json.dumps(res, ensure_ascii=False, indent=2) + "</pre>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    return jsonify(res)

# ---------- エントリポイント（最後に置く） ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
