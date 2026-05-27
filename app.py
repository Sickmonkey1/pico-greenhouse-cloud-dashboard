from flask import Flask, request, jsonify, render_template_string
from datetime import datetime, timezone
from collections import deque
import os
import time

app = Flask(__name__)

API_KEY = os.environ.get("PICO_API_KEY", "change-this-key")

MAX_HISTORY = 300
history = deque(maxlen=MAX_HISTORY)

latest_data = {
    "timestamp": "No data yet",
    "temperature": None,
    "humidity": None,
    "pressure": None,
    "status": "WAITING",
    "prediction": "Waiting for Pico data",
    "version": "--",
    "last_seen": "Never",
    "last_seen_epoch": 0
}


def now_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value):
    try:
        return float(value)
    except:
        return None


def get_min_max(key):
    values = [item[key] for item in history if item.get(key) is not None]

    if not values:
        return None, None

    return min(values), max(values)


def get_pressure_trend():
    if len(history) < 5:
        return "Collecting pressure trend"

    first = history[0].get("pressure")
    last = history[-1].get("pressure")

    if first is None or last is None:
        return "Collecting pressure trend"

    change = last - first

    if change <= -2.0:
        return "Pressure falling - storm/rain possible"
    elif change >= 2.0:
        return "Pressure rising - weather improving"
    else:
        return "Pressure stable"


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
            background: linear-gradient(135deg, #b9cbea, #e7f0ff);
            color: #111827;
            padding: 18px;
        }

        .container {
            max-width: 1050px;
            margin: auto;
        }

        .header {
            background: rgba(255, 255, 255, 0.92);
            border-radius: 28px;
            padding: 22px;
            box-shadow: 0 18px 40px rgba(40, 60, 90, 0.18);
            margin-bottom: 18px;
        }

        .title {
            font-size: 30px;
            font-weight: 800;
            margin-bottom: 6px;
        }

        .subtitle {
            color: #6b7280;
            font-size: 14px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            gap: 16px;
        }

        .card {
            background: rgba(255, 255, 255, 0.94);
            border-radius: 26px;
            padding: 20px;
            box-shadow: 0 18px 40px rgba(40, 60, 90, 0.16);
        }

        .span-4 {
            grid-column: span 4;
        }

        .span-6 {
            grid-column: span 6;
        }

        .span-8 {
            grid-column: span 8;
        }

        .span-12 {
            grid-column: span 12;
        }

        .label {
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 6px;
        }

        .big-temp {
            font-size: 72px;
            font-weight: 300;
            line-height: 1;
        }

        .value {
            font-size: 32px;
            font-weight: 800;
        }

        .small {
            font-size: 13px;
            color: #6b7280;
        }

        .status-pill {
            display: inline-block;
            margin-top: 10px;
            padding: 12px 18px;
            border-radius: 999px;
            color: white;
            font-weight: 800;
            background: #35e58a;
        }

        .warning {
            background: #ef4444 !important;
        }

        .offline {
            background: #f97316 !important;
        }

        .metric-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 12px;
        }

        .mini-box {
            background: #f4f8ff;
            border-radius: 18px;
            padding: 12px;
        }

        canvas {
            width: 100%;
            height: 170px;
            display: block;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        th, td {
            text-align: left;
            padding: 9px;
            border-bottom: 1px solid #e5e7eb;
        }

        th {
            color: #6b7280;
            font-weight: 700;
        }

        .footer {
            text-align: center;
            color: #6b7280;
            margin-top: 20px;
            font-size: 12px;
        }

        @media (max-width: 800px) {
            .span-4, .span-6, .span-8, .span-12 {
                grid-column: span 12;
            }

            .big-temp {
                font-size: 64px;
            }
        }
    </style>
</head>

<body>
<div class="container">

    <div class="header">
        <div class="title">Nathan's Greenhouse Weather Station</div>
        <div class="subtitle">
            Live Pico W environmental dashboard • SD card logging on device • Cloud display on Render
        </div>
    </div>

    <div class="grid">

        <div class="card span-4">
            <div class="label">Current Temperature</div>
            <div class="big-temp"><span id="temperature">--</span>°C</div>
            <div class="small" id="timestamp">No data yet</div>
            <div class="status-pill" id="status">WAITING</div>
        </div>

        <div class="card span-4">
            <div class="label">Humidity</div>
            <div class="value"><span id="humidity">--</span>%</div>

            <div class="metric-row">
                <div class="mini-box">
                    <div class="label">Min</div>
                    <b><span id="hum_min">--</span>%</b>
                </div>
                <div class="mini-box">
                    <div class="label">Max</div>
                    <b><span id="hum_max">--</span>%</b>
                </div>
            </div>
        </div>

        <div class="card span-4">
            <div class="label">Pressure</div>
            <div class="value"><span id="pressure">--</span> hPa</div>

            <div class="metric-row">
                <div class="mini-box">
                    <div class="label">Min</div>
                    <b><span id="pressure_min">--</span></b>
                </div>
                <div class="mini-box">
                    <div class="label">Max</div>
                    <b><span id="pressure_max">--</span></b>
                </div>
            </div>
        </div>

        <div class="card span-6">
            <div class="label">Temperature Trend</div>
            <canvas id="tempChart"></canvas>
        </div>

        <div class="card span-6">
            <div class="label">Humidity Trend</div>
            <canvas id="humChart"></canvas>
        </div>

        <div class="card span-8">
            <div class="label">Pressure Trend</div>
            <canvas id="pressureChart"></canvas>
        </div>

        <div class="card span-4">
            <div class="label">Weather Prediction</div>
            <h2 id="prediction">Waiting for Pico data</h2>

            <div class="mini-box">
                <div class="label">Last Seen</div>
                <b id="last_seen">Never</b>
            </div>

            <div class="mini-box">
                <div class="label">Pico Code Version</div>
                <b id="version">--</b>
            </div>
        </div>

        <div class="card span-4">
            <div class="label">Temperature Min / Max</div>
            <div class="metric-row">
                <div class="mini-box">
                    <div class="label">Min Temp</div>
                    <b><span id="temp_min">--</span>°C</b>
                </div>
                <div class="mini-box">
                    <div class="label">Max Temp</div>
                    <b><span id="temp_max">--</span>°C</b>
                </div>
            </div>
        </div>

        <div class="card span-8">
            <div class="label">Recent Readings</div>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Temp</th>
                        <th>Humidity</th>
                        <th>Pressure</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="recentTable">
                    <tr><td colspan="5">Waiting for data...</td></tr>
                </tbody>
            </table>
        </div>

    </div>

    <div class="footer">
        Dashboard refreshes every 10 seconds. Long-term raw data is stored on the Pico SD card.
    </div>

</div>

<script>
function fmt(value, decimals = 1) {
    if (value === null || value === undefined || value === "--") return "--";
    let n = Number(value);
    if (isNaN(n)) return "--";
    return n.toFixed(decimals);
}

function drawChart(canvasId, values, label) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas.getContext("2d");

    const width = canvas.clientWidth;
    const height = canvas.clientHeight;

    canvas.width = width;
    canvas.height = height;

    ctx.clearRect(0, 0, width, height);

    ctx.lineWidth = 2;
    ctx.strokeStyle = "#d1d5db";

    for (let i = 0; i <= 4; i++) {
        let y = (height / 4) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
    }

    const clean = values.filter(v => v !== null && v !== undefined && !isNaN(Number(v))).map(Number);

    if (clean.length < 2) {
        ctx.fillStyle = "#6b7280";
        ctx.font = "14px Arial";
        ctx.fillText("Waiting for more data...", 12, 30);
        return;
    }

    const min = Math.min(...clean);
    const max = Math.max(...clean);
    const range = max - min || 1;

    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    ctx.beginPath();

    clean.forEach((value, index) => {
        const x = (index / (clean.length - 1)) * width;
        const y = height - ((value - min) / range) * (height - 20) - 10;

        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });

    ctx.stroke();

    ctx.fillStyle = "#111827";
    ctx.font = "13px Arial";
    ctx.fillText(label + "  Min: " + min.toFixed(1) + "  Max: " + max.toFixed(1), 12, 18);
}

async function loadData() {
    try {
        const response = await fetch("/api/latest");
        const data = await response.json();

        document.getElementById("timestamp").innerHTML = data.timestamp;
        document.getElementById("temperature").innerHTML = fmt(data.temperature);
        document.getElementById("humidity").innerHTML = fmt(data.humidity);
        document.getElementById("pressure").innerHTML = fmt(data.pressure);
        document.getElementById("status").innerHTML = data.status;
        document.getElementById("prediction").innerHTML = data.prediction;
        document.getElementById("last_seen").innerHTML = data.last_seen;
        document.getElementById("version").innerHTML = data.version;

        document.getElementById("temp_min").innerHTML = fmt(data.stats.temp_min);
        document.getElementById("temp_max").innerHTML = fmt(data.stats.temp_max);
        document.getElementById("hum_min").innerHTML = fmt(data.stats.hum_min);
        document.getElementById("hum_max").innerHTML = fmt(data.stats.hum_max);
        document.getElementById("pressure_min").innerHTML = fmt(data.stats.pressure_min);
        document.getElementById("pressure_max").innerHTML = fmt(data.stats.pressure_max);

        const statusEl = document.getElementById("status");
        statusEl.className = "status-pill";

        if (data.offline) {
            statusEl.innerHTML = "OFFLINE";
            statusEl.classList.add("offline");
        } else if (data.status !== "OK") {
            statusEl.classList.add("warning");
        }

        drawChart("tempChart", data.history.map(x => x.temperature), "Temperature °C");
        drawChart("humChart", data.history.map(x => x.humidity), "Humidity %");
        drawChart("pressureChart", data.history.map(x => x.pressure), "Pressure hPa");

        const recent = data.history.slice(-8).reverse();
        const table = document.getElementById("recentTable");

        if (recent.length === 0) {
            table.innerHTML = '<tr><td colspan="5">Waiting for data...</td></tr>';
        } else {
            table.innerHTML = recent.map(row => `
                <tr>
                    <td>${row.timestamp}</td>
                    <td>${fmt(row.temperature)}°C</td>
                    <td>${fmt(row.humidity)}%</td>
                    <td>${fmt(row.pressure)} hPa</td>
                    <td>${row.status}</td>
                </tr>
            `).join("");
        }

    } catch (error) {
        const statusEl = document.getElementById("status");
        statusEl.innerHTML = "OFFLINE";
        statusEl.className = "status-pill offline";
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
    temp_min, temp_max = get_min_max("temperature")
    hum_min, hum_max = get_min_max("humidity")
    pressure_min, pressure_max = get_min_max("pressure")

    last_seen_epoch = latest_data.get("last_seen_epoch", 0)
    offline = False

    if last_seen_epoch == 0:
        offline = True
    elif time.time() - last_seen_epoch > 180:
        offline = True

    data = {
        "timestamp": latest_data.get("timestamp", "No data yet"),
        "temperature": latest_data.get("temperature"),
        "humidity": latest_data.get("humidity"),
        "pressure": latest_data.get("pressure"),
        "status": latest_data.get("status", "WAITING"),
        "prediction": latest_data.get("prediction", "Waiting for Pico data"),
        "version": latest_data.get("version", "--"),
        "last_seen": latest_data.get("last_seen", "Never"),
        "offline": offline,
        "stats": {
            "temp_min": temp_min,
            "temp_max": temp_max,
            "hum_min": hum_min,
            "hum_max": hum_max,
            "pressure_min": pressure_min,
            "pressure_max": pressure_max
        },
        "history": list(history)
    }

    return jsonify(data)


@app.route("/api/update", methods=["POST"])
def api_update():
    global latest_data

    key = request.headers.get("X-API-KEY")

    if key != API_KEY:
        return jsonify({"error": "unauthorised"}), 401

    data = request.get_json(force=True)

    timestamp = data.get("timestamp", now_string())
    temp = safe_float(data.get("temperature"))
    humidity = safe_float(data.get("humidity"))
    pressure = safe_float(data.get("pressure"))
    status = data.get("status", "UNKNOWN")
    version = data.get("version", "--")

    prediction = data.get("prediction", "")

    reading = {
        "timestamp": timestamp,
        "temperature": temp,
        "humidity": humidity,
        "pressure": pressure,
        "status": status,
        "version": version,
        "server_time": now_string()
    }

    history.append(reading)

    pressure_prediction = get_pressure_trend()

    if prediction:
        final_prediction = prediction
    else:
        final_prediction = pressure_prediction

    latest_data = {
        "timestamp": timestamp,
        "temperature": temp,
        "humidity": humidity,
        "pressure": pressure,
        "status": status,
        "prediction": final_prediction,
        "version": version,
        "last_seen": now_string(),
        "last_seen_epoch": time.time()
    }

    return jsonify({"message": "data received", "latest": latest_data})


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "online",
        "history_count": len(history),
        "last_seen": latest_data.get("last_seen", "Never")
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
