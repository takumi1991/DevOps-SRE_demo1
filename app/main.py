from flask import Flask, Response
import random, time

app = Flask(__name__)

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
    text = f"# HELP response_latency_seconds Demo latency\n# TYPE response_latency_seconds gauge\nresponse_latency_seconds {latency}\n"
    return Response(text, mimetype="text/plain; version=0.0.4")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
