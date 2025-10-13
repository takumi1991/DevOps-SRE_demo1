from flask import Flask, request, jsonify
from flask import Response
import json, random, uuid

app = Flask(__name__)

# --- 既存の簡易エンドポイント ---
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

# --- 追加: 性格診断フォーム ---
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

# --- 追加: 発行API（まずはローカル計算のみ / ストレージ保存なし） ---
@app.route("/mint", methods=["POST"])
def mint():
    data = request.get_json(silent=True) or request.form.to_dict()
    token_id = str(uuid.uuid4())

    # テキトーに能力値を振る（デモ）
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
        "asset_url": None,  # 後で GCS 保存を入れるならここに URL を出す
    }

    # HTML で返したいとき（フォームからのアクセスを見やすく）
    if "text/html" in request.headers.get("Accept", "") and not request.is_json:
        return (
            "<pre>" + json.dumps(res, ensure_ascii=False, indent=2) + "</pre>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    return jsonify(res)
    
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
