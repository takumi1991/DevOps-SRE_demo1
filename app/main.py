from flask import Flask, request, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import os, json, random, uuid
from google.cloud import storage  # GCS に書き込む用

app = Flask(__name__)
# Cloud Run のリバースプロキシヘッダを信頼
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ---------------- 基本動作確認用 ----------------
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

# --- 追加：環境変数のデバッグ出力 ---
@app.route("/debug/env", methods=["GET"])
def debug_env():
    masked = {}
    for k, v in os.environ.items():
        masked[k] = "***" if any(x in k for x in ["KEY","SECRET","TOKEN","PASSWORD"]) else v
    return jsonify({"env": masked})

# ---------------- フォーム（性格診断） ----------------
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
  <p><small><a href="/metrics">/metrics</a> ・ <a href="/health">/health</a></small></p>
</body>
</html>
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

    res = {
        "ok": True,
        "token_id": token_id,
        "horse": horse,
        "permalink": f"{request.url_root}quiz?token={token_id}",
        "asset_url": None,
    }

    # ---- GCS に SVG を保存（成功したら asset_url をセット）----
    bucket_name = os.getenv("GCS_BUCKET")
    if bucket_name:
        try:
            svg = _svg_for(horse).encode("utf-8")
            path = f"horses/{token_id}.svg"
            client = storage.Client()  # Cloud Run のデフォルトSA
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(path)
            blob.upload_from_string(svg, content_type="image/svg+xml")
            res["asset_url"] = f"https://storage.googleapis.com/{bucket_name}/{path}"
        except Exception as e:
            # 失敗してもJSONには ok と token は返す（asset_urlはNone）
            print(f"[GCS][ERROR] {e}")

    # ←← ここが今回の改修：フォーム経由ならHTMLでリンクを表示
    is_form_post = (request.content_type or "").startswith("application/x-www-form-urlencoded") \
                   or "text/html" in (request.headers.get("Accept") or "")
    if is_form_post and not request.is_json:
        # クリック可能なリンクとシェア用パーマリンクを表示
        asset_line = (f'<p>画像SVG: <a href="{res["asset_url"]}" target="_blank">{res["asset_url"]}</a></p>'
                      if res["asset_url"] else "<p>画像の保存に失敗しました（asset_url=None）。</p>")
        html = f"""
<!doctype html>
<html lang="ja"><meta charset="utf-8"><title>Mint結果</title>
<body>
  <h1>発行完了 🎉</h1>
  <p>Token ID: <code>{res["token_id"]}</code></p>
  {asset_line}
  <p>パーマリンク: <a href="{res["permalink"]}" target="_blank">{res["permalink"]}</a></p>
  <h2>Horse</h2>
  <pre>{json.dumps(res["horse"], ensure_ascii=False, indent=2)}</pre>
  <p><a href="/quiz">← もう一度診断する</a></p>
</body></html>
"""
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    # API（JSONクライアント）にはJSONで返す
    return jsonify(res)

def _svg_for(horse: dict) -> str:
    # SVGに馬のシルエットを簡易描画
    body_color = "#654321"  # 茶色ベース
    accent = "#000000"      # 黒いたてがみ・脚
    text_color = "#222222"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
  <rect width="100%" height="100%" fill="white"/>
  
  <!-- 馬の胴体 -->
  <ellipse cx="320" cy="200" rx="120" ry="60" fill="{body_color}" />
  
  <!-- 馬の首と頭 -->
  <rect x="410" y="120" width="30" height="60" fill="{body_color}" />
  <circle cx="440" cy="120" r="20" fill="{body_color}" />
  
  <!-- 脚 -->
  <rect x="260" y="250" width="15" height="70" fill="{accent}" />
  <rect x="300" y="250" width="15" height="70" fill="{accent}" />
  <rect x="360" y="250" width="15" height="70" fill="{accent}" />
  <rect x="400" y="250" width="15" height="70" fill="{accent}" />

  <!-- 尾 -->
  <path d="M 200 200 Q 180 240 220 220" stroke="{accent}" stroke-width="10" fill="none"/>

  <!-- テキスト -->
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
