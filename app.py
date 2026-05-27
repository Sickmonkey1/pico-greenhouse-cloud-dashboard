from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import os

app = Flask(__name__)

API_KEY = os.environ.get("PICO_API_KEY", "change-this-key")

latest_data = {
    "timestamp": "No data yet",
    "temperature": "--",
    "humidity": "--",
    "pressure": "--",
    "status": "WAITING",
    "prediction": "Waiting for Pico data",
    "version": "--",
    "last_seen": "Never"
}

page = """
<!DOCTYPE html>
<html>
<head>
    <title>Nathan's Greenhouse Weather Station</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #dcecff, #7f9fc4);
            color: #15192e;
            display: flex;
            justify-content: center;
            padding: 20px;
        }

        .card {
            width: 390px;
            background: rgba(255,255,255,0.95);
            border-radius: 28px;
            padding: 24px;
            box-shadow: 0 20px 45px rgba(40,60,90,0.25);
            text-align: center;
        }

        .title {
            font-size: 25px;
            font-weight: 700;
        }

        .time {
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 16px;
        }

        .main-temp {
            font-size: 68px;
            font-weight: 300;
            margin-top: 8px;
        }

        .subtext {
            font-size: 14px;
            color: #6b7280;
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 18px;
        }

        .box {
            background: #f4f8ff;
            border-radius: 18px;
            padding: 12px;
        }

        .label {
            font-size: 12px;
            color: #6b7280;
        }

        .value {
            font-size: 20px;
            font-weight: 600;
        }

        .status {
            margin-top: 18px;
            padding: 12px;
            border-radius: 18px;
            color: white;
            font-weight: 700;
            background: #35e58a;
        }

        .panel {
            margin-top: 16px;
            background: #f4f8ff;
            border-radius: 18px;
            padding: 12px;
        }

        .footer {
            margin-top: 14px;
            font-size: 11px;
            color: #6b7280;
        }
    </style>
</head>

<body>
<div class="card">

    <div class="title">Greenhouse Weather Station</div>
    <div class="time" id="timestamp">Loading...</div>

    <div class="main-temp" id="temperature">--°</div>
    <div class="subtext">Temperature</div>

    <div class="grid">
        <div class="box">
            <div class="label">Humidity</div>
            <div class="value" id="humidity">--%</div>
        </div>

        <div class="box">
            <div class="label">Pressure</div>
            <div class="value" id="pressure">-- hPa</div>
        </div>
    </div>

    <div class="status" id="status">WAITING</div>

    <div class="panel">
        <b>Weather Prediction</b>
        <p id="prediction">Waiting for Pico data</p>
    </div>

    <div class="panel">
        <b>System</b>
        <p>Last seen: <span id="last_seen">--</span></p>
        <p>Version: <span id="version">--</span></p>
    </div>

    <div class="footer">Public live dashboard • Updates every 10 seconds</div>
</div>

<script>
async function loadData() {
    try {
        const response = await fetch("/api/latest");
        const data = await response.json();

        document.getElementById("timestamp").innerHTML = data.timestamp;
        document.getElementById("temperature").innerHTML = data.temperature + "&deg;C";
        document.getElementById("humidity").innerHTML = data.humidity + "%";
        document.getElementById("pressure").innerHTML = data.pressure + " hPa";
        document.getElementById("status").innerHTML = data.status;
        document.getElementById("prediction").innerHTML = data.prediction;
        document.getElementById("version").innerHTML = data.version;
        document.getElementById("last_seen").innerHTML = data.last_seen;

        if (data.status === "OK") {
            document.getElementById("status").style.background = "#35e58a";
        } else {
            document.getElementById("status").style.background = "#ff5c5c";
        }

    } catch (error) {
        document.getElementById("status").innerHTML = "OFFLINE";
        document.getElementById("status").style.background = "#ff5c5c";
    }
}

loadData();
setInterval(loadData, 10000);
</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(page)

@app.route("/api/latest")
def api_latest():
    return jsonify(latest_data)

@app.route("/api/update", methods=["POST"])
def api_update():
    global latest_data

    key = request.headers.get("X-API-KEY")

    if key != API_KEY:
        return jsonify({"error": "unauthorised"}), 401

    data = request.get_json(force=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    latest_data = {
        "timestamp": data.get("timestamp", now),
        "temperature": data.get("temperature", "--"),
        "humidity": data.get("humidity", "--"),
        "pressure": data.get("pressure", "--"),
        "status": data.get("status", "UNKNOWN"),
        "prediction": data.get("prediction", "No prediction"),
        "version": data.get("version", "--"),
        "last_seen": now
    }

    return jsonify({"message": "data received", "received": latest_data})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
