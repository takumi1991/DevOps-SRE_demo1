from flask import Flask, request, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import os, json, random, uuid, traceback
from google.cloud import storage

app = Flask(__name__)
# Cloud Run のリバースプロキシヘッダを信頼
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ===== 共通ユーティリティ =====
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

def _env_snapshot():
    # 最低限の環境と実行ID
    return {
        "PORT": os.getenv("PORT"),
        "GCS_BUCKET": os.getenv("GCS_BUCKET"),
        "K_SERVICE": os.getenv("K_SERVICE"),
        "K_REVISION": os.getenv("K_REVISION"),
        "K_CONFIGURATION": os.getenv("K_CONFIGURATION"),
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT"),
        "SERVICE_ACCOUNT": os.getenv("GOOGLE_SERVICE_ACCOUNT", "unknown"),
    }

# ===== ヘルス & ベーシック =====
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

# ===== デバッグ用 =====
@app.route("/debug/env")
def debug_env():
    # JSON で返す（jq で食べられるように）
    return jsonify(_env_snapshot())

# ===== ミントUI =====
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

# ===== ミントAPI =====
@app.route("/mint", methods=["POST"])
def mint():
    debug = {"env": _env_snapshot(), "steps": []}

    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        debug["input"] = data
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
            "debug": debug,  # デモ中はそのまま返す（不要になったら消す）
        }

        # --- GCS 保存 ---
        bucket_name = os.getenv("GCS_BUCKET")
        debug["steps"].append({"bucket_name_seen": bucket_name})

        if bucket_name:
            try:
                svg = _svg_for(horse).encode("utf-8")
                path = f"horses/{token_id}.svg"
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(path)
                blob.upload_from_string(svg, content_type="image/svg+xml")
                res["asset_url"] = f"https://storage.googleapis.com/{bucket_name}/{path}"
                debug["steps"].append({"upload": "ok", "path": path})
            except Exception as e:
                debug["steps"].append({"upload": "error", "message": str(e), "trace": traceback.format_exc()})
        else:
            debug["steps"].append({"note": "GCS_BUCKET env not set"})

        # HTMLで見やすく
        if "text/html" in request.headers.get("Accept", "") and not request.is_json:
            return (
                "<pre>" + json.dumps(res, ensure_ascii=False, indent=2) + "</pre>",
                200, {"Content-Type": "text/html; charset=utf-8"},
            )
        return jsonify(res)

    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc(), "debug": debug}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
