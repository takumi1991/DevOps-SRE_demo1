# main.py
from flask import Flask, request, Response, jsonify, redirect
from flask import render_template_string
import os, json, uuid, random, time, traceback

# --- Gemini (text) ---
# ライブラリ: google-genai
# pip: google-genai>=0.3.0
try:
    from google import genai
except Exception:
    genai = None

# --- GCS (任意: 保存先) ---
# pip: google-cloud-storage
try:
    from google.cloud import storage
except Exception:
    storage = None

app = Flask(__name__)

###############################################################################
# 既存の簡易エンドポイント
###############################################################################
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
    # なんちゃってレイテンシをPrometheus形式で返す
    latency = random.random()
    text = (
        "# HELP response_latency_seconds Demo latency\n"
        "# TYPE response_latency_seconds gauge\n"
        f"response_latency_seconds {latency}\n"
    )
    return Response(text, mimetype="text/plain; version=0.0.4")


###############################################################################
# 追加: 性格診断UI (/quiz) と 発行処理 (/mint)
###############################################################################
QUIZ_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>性格診断 → 馬トークン発行（デモ）</title>
  <style>
    body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; margin: 24px; }
    h1 { font-size: 20px; margin-bottom: 8px; }
    .card { max-width: 680px; border: 1px solid #e5e5e5; border-radius: 12px; padding: 16px; }
    .q { margin: 12px 0; }
    button { all: unset; background: #1a73e8; color: #fff; padding: 10px 16px; border-radius: 8px; cursor: pointer; }
    button:disabled { background: #9bbcf0; cursor: wait; }
    .small { color: #666; font-size: 12px; }
    .result { margin-top: 20px; padding: 12px; border: 1px dashed #ddd; border-radius: 8px; display:none; }
    .link { margin-top: 8px; }
    input[type="text"], select { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 6px; }
    label { display:block; font-weight:600; margin-bottom:4px; }
  </style>
</head>
<body>
  <h1>性格診断 → 馬トークン発行（デモ）</h1>
  <div class="card">
    <div class="q">
      <label>1. 直感派？計画派？</label>
      <select id="q1">
        <option>直感で動く</option>
        <option>しっかり計画する</option>
        <option>状況次第で切替える</option>
      </select>
    </div>
    <div class="q">
      <label>2. チーム戦と個人戦どちらが得意？</label>
      <select id="q2">
        <option>チーム戦が好き</option>
        <option>個人で黙々とやる方が得意</option>
        <option>半々くらい</option>
      </select>
    </div>
    <div class="q">
      <label>3. 朝型？夜型？</label>
      <select id="q3">
        <option>完全に朝型</option>
        <option>完全に夜型</option>
        <option>どちらでもない</option>
      </select>
    </div>
    <div class="q">
      <label>4. 好きなフィールド（ざっくり）</label>
      <select id="q4">
        <option>スピード・素早さ</option>
        <option>スタミナ・粘り強さ</option>
        <option>知性・戦略性</option>
        <option>運の良さ・豪運</option>
      </select>
    </div>
    <div class="q">
      <label>5. 好きな色</label>
      <input id="q5" type="text" placeholder="例: 青 / 紫 / ゴールド など"/>
    </div>

    <button id="btn">診断して発行</button>
    <div class="small">※ デモ用途。Gemini (text) を使用。画像はSVGを自動生成し、必要に応じてGCSへ保存します。</div>

    <div id="result" class="result">
      <div id="msg"></div>
      <div class="link" id="links"></div>
    </div>
  </div>

<script>
  const b = document.getElementById('btn');
  const r = document.getElementById('result');
  const msg = document.getElementById('msg');
  const links = document.getElementById('links');

  b.addEventListener('click', async () => {
    b.disabled = true; r.style.display = 'block';
    msg.textContent = '発行中…(10～20秒)';
    links.innerHTML = '';
    try {
      const payload = {
        q1: document.getElementById('q1').value,
        q2: document.getElementById('q2').value,
        q3: document.getElementById('q3').value,
        q4: document.getElementById('q4').value,
        q5: document.getElementById('q5').value
      };
      const res = await fetch('/mint', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      if (!res.ok) throw new Error('HTTP '+res.status);
      const data = await res.json();
      msg.innerHTML = `<b>${data.horse.name}</b> を発行しました！<br/>タイプ: ${data.horse.temperament} / ステータス: 速度${data.horse.speed}, スタミナ${data.horse.stamina}, スキル${data.horse.skill}<br/>キャッチフレーズ: 「${data.horse.catchphrase}」`;

      if (data.asset_url) {
        links.innerHTML += `<div>カード画像: <a href="${data.asset_url}" target="_blank">${data.asset_url}</a></div>`;
      }
      if (data.permalink) {
        links.innerHTML += `<div>共有用リンク: <a href="${data.permalink}" target="_blank">${data.permalink}</a></div>`;
      }
    } catch (e) {
      msg.textContent = 'エラー: ' + e.message;
    } finally {
      b.disabled = false;
    }
  });
</script>
</body>
</html>
"""

@app.route("/quiz")
def quiz():
    return render_template_string(QUIZ_HTML)


def get_gemini_client():
    """Geminiクライアントを返す（APIキーは環境変数 GEMINI_API_KEY）"""
    if genai is None:
        raise RuntimeError("google-genai がインストールされていません")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("環境変数 GEMINI_API_KEY が未設定です（Cloud Run のシークレット連携を確認）")
    return genai.Client(api_key=api_key)

def ask_gemini_for_horse(profile_text: str) -> dict:
    """
    Gemini に性格診断テキストを渡し、馬の情報（JSON）を生成してもらう。
    """
    client = get_gemini_client()
    prompt = f"""
あなたはファンタジー競走馬のデザイナーです。
以下のユーザーの性格診断の要約を読み、馬の設定を JSON で1つ出力してください。

# 出力 JSON 仕様（必ずこのキーのみ、数値は 1〜10）
{{
  "name": "短い名前（日本語または英語）",
  "temperament": "性格説明（10〜20文字）",
  "colorScheme": "配色（例: 青×黒 / 紫×金 など）",
  "speed": 7,
  "stamina": 5,
  "skill": 6,
  "catchphrase": "短い決め台詞"
}}

# ユーザー要約:
{profile_text}
"""

    # text生成
    res = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[{"role":"user","parts":[prompt]}],
        config={"temperature":0.7}
    )
    text = res.text or ""
    # コードブロック/JSON抽出の素直なパース
    j = None
    try:
        # JSONだけにしてくれる場合もあるが、一応 { から } までを拾う
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            j = json.loads(text[start:end+1])
    except Exception:
        j = None

    if not isinstance(j, dict):
        # フォールバック
        j = {
            "name": "NoName",
            "temperament": "穏やか",
            "colorScheme": "青×白",
            "speed": 6,
            "stamina": 6,
            "skill": 6,
            "catchphrase": "行くぞ！",
        }
    # 値の範囲など軽い正規化
    for k in ("speed","stamina","skill"):
        try:
            v = int(j.get(k,6))
            j[k] = max(1, min(10, v))
        except Exception:
            j[k] = 6
    return j

def make_svg_card(h: dict, token_id: str) -> str:
    """
    画像コストを抑えるため、まずは SVG を生成（ブラウザ/Discord でもプレビュー可）。
    必要なら GCS に保存し、公開URLを返す。
    """
    # 配色の決定（colorScheme を優先、なければ簡易に色決め）
    prim = "#4F46E5"  # indigo-600
    sec  = "#0EA5E9"  # sky-500
    if "紫" in h.get("colorScheme",""): prim, sec = ("#7C3AED", "#A78BFA")
    if "金" in h.get("colorScheme",""): sec = "#F59E0B"
    if "黒" in h.get("colorScheme",""): prim = "#111827"

    name = h.get("name","NoName")
    temp = h.get("temperament","穏やか")
    speed = h.get("speed",6)
    stamina = h.get("stamina",6)
    skill = h.get("skill",6)
    line2 = f"S:{speed}  St:{stamina}  Sk:{skill}"
    catch = h.get("catchphrase","行くぞ！")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="420">
  <defs>
    <linearGradient id="g" x1="0" x2="1">
      <stop offset="0%" stop-color="{prim}"/>
      <stop offset="100%" stop-color="{sec}"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#g)"/>
  <circle cx="120" cy="210" r="80" fill="#fff" fill-opacity="0.15"/>
  <rect x="40" y="300" width="720" height="90" rx="10" fill="#000" fill-opacity="0.2"/>
  <text x="40" y="80" fill="#fff" font-size="26" font-family="Segoe UI, sans-serif">Horse Token</text>
  <text x="40" y="140" fill="#fff" font-size="48" font-weight="700" font-family="Segoe UI, sans-serif">{name}</text>
  <text x="40" y="185" fill="#f1f5f9" font-size="22" font-family="Segoe UI, sans-serif">{temp} / {h.get('colorScheme','')}</text>
  <text x="40" y="230" fill="#e2e8f0" font-size="22" font-family="Segoe UI, sans-serif">{line2}</text>
  <text x="40" y="345" fill="#fff" font-size="24" font-family="Segoe UI, sans-serif">「{catch}」</text>
  <text x="620" y="395" text-anchor="end" fill="#cbd5e1" font-size="14" font-family="monospace">token:{token_id[:8]}</text>
</svg>"""
    return svg

def save_svg_to_gcs(svg: str, token_id: str) -> str | None:
    """
    GCS バケット (環境変数 GCS_BUCKET) に SVG を保存し、公開URLを返す。
    バケット未設定/権限なし等なら None を返す。
    """
    bucket_name = os.getenv("GCS_BUCKET")
    if not bucket_name or storage is None:
        return None
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(f"horses/{token_id}.svg")
        blob.upload_from_string(svg, content_type="image/svg+xml")
        # 公開リンク化（バケットが公開可能設定なら表示可能）
        try:
            blob.make_public()
            return blob.public_url
        except Exception:
            # 署名付きURL（1日）
            url = blob.generate_signed_url(expiration=60*60*24, method="GET")
            return url
    except Exception:
        # GCSが無くてもサービスは動作させたい
        return None

@app.route("/mint", methods=["POST"])
def mint():
    """
    質問→性格テキスト→Geminiで馬設定→SVGカード生成→（任意でGCS保存）→結果返却
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        data = {}

    profile_text = (
        f"Q1:{data.get('q1','')}, Q2:{data.get('q2','')}, "
        f"Q3:{data.get('q3','')}, Q4:{data.get('q4','')}, Q5(色):{data.get('q5','')}"
    )

    try:
        horse = ask_gemini_for_horse(profile_text)
    except Exception as e:
        # Geminiが使えない/キー未設定でもデモ継続
        horse = {
            "name":"Fallback",
            "temperament":"素直",
            "colorScheme":"青×白",
            "speed":6,"stamina":6,"skill":6,
            "catchphrase":"がんばるぞ！"
        }

    token_id = str(uuid.uuid4())
    svg = make_svg_card(horse, token_id)
    asset_url = save_svg_to_gcs(svg, token_id)  # 失敗しても None 可

    # 共有用（パーマリンク風）: ここではクエリに詰めるだけの簡易実装
    # 本番は Firestore/DB で token_id -> メタデータ を保持推奨
    base = request.host_url.rstrip("/")
    permalink = f"{base}/quiz?token={token_id}"

    return jsonify({
        "ok": True,
        "token_id": token_id,
        "horse": horse,
        "asset_url": asset_url,      # GCSに保存できたらそのURL
        "permalink": permalink       # 簡易共有リンク
    })
###############################################################################

if __name__ == "__main__":
    # Cloud Run では PORT 環境変数が渡される
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
