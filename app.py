from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from collections import deque
import os
import time 

app = Flask(__name__)

# ========================= 
# CONFIG
# =========================

API_KEY = os.environ.get("PICO_API_KEY", "change-this-key")
UPDATE_PIN = os.environ.get("UPDATE_PIN", "1234")

MAX_HISTORY = 1440
history = deque(maxlen=MAX_HISTORY)

pending_pico_update = {
    "requested": False,
    "requested_at": None,
    "message": "No update pending"
}

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


# =========================
# HELPERS
# =========================

def now_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value):
    try:
        if value is None:
            return None

        value = float(value)

        if value != value:
            return None

        return value
    except:
        return None


def get_min_max(key):
    values = [item[key] for item in history if item.get(key) is not None]

    if not values:
        return None, None

    return min(values), max(values)


def recent_values(key, count):
    values = [item.get(key) for item in list(history)[-count:]]
    return [v for v in values if v is not None]


def get_change(key, count):
    values = recent_values(key, count)

    if len(values) < 2:
        return None

    return values[-1] - values[0]


def get_weather_prediction():
    if len(history) < 10:
        return "Collecting weather trend"

    pressure_30 = get_change("pressure", 30)
    pressure_60 = get_change("pressure", 60)
    humidity_30 = get_change("humidity", 30)
    temp_30 = get_change("temperature", 30)

    latest_pressure = latest_data.get("pressure")
    latest_humidity = latest_data.get("humidity")

    if latest_pressure is None or latest_humidity is None:
        return "Collecting weather trend"

    if pressure_30 is None:
        return "Collecting weather trend"

    if pressure_30 <= -1.0 and humidity_30 is not None and humidity_30 >= 3:
        return "Pressure falling + humidity rising - rain/storm possible"

    if pressure_30 <= -1.5:
        return "Pressure falling quickly - unsettled weather possible"

    if pressure_60 is not None and pressure_60 <= -2.0:
        return "Pressure falling over the hour - rain possible"

    if pressure_30 >= 1.0 and humidity_30 is not None and humidity_30 <= -2:
        return "Pressure rising + humidity dropping - clearing/improving"

    if pressure_30 >= 1.5:
        return "Pressure rising - weather improving"

    if latest_humidity >= 90:
        return "Very humid - damp/rainy conditions possible"

    if latest_humidity >= 85:
        return "Humidity high - moisture in the air"

    if temp_30 is not None and temp_30 <= -1.0 and humidity_30 is not None and humidity_30 >= 2:
        return "Cooling with humidity rising - rain nearby possible"

    return "Pressure stable"


# =========================
# WEB PAGE
# =========================

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

        .span-4 { grid-column: span 4; }
        .span-6 { grid-column: span 6; }
        .span-8 { grid-column: span 8; }
        .span-12 { grid-column: span 12; }

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
            margin-top: 10px;
        }

        canvas {
            width: 100%;
            height: 225px;
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

        button {
            cursor: pointer;
        }

        .update-button {
            width: 100%;
            margin-top: 12px;
            padding: 14px;
            border: none;
            border-radius: 18px;
            background: #111827;
            color: white;
            font-weight: 800;
            font-size: 15px;
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

            canvas {
                height: 210px;
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

            <div class="mini-box">
                <div class="label">Update Status</div>
                <b id="update_status">No update pending</b>
            </div>

            <button class="update-button" onclick="requestPicoUpdate()">
                Update Pico from GitHub
            </button>
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

function formatTime24(timestamp) {
    if (!timestamp) return "";

    let text = String(timestamp);

    // Expected Pico format: YYYY-MM-DD HH:MM:SS
    if (text.includes(" ")) {
        let timePart = text.split(" ")[1];
        return timePart.substring(0, 5);
    }

    return text.substring(0, 5);
}

function drawChart(canvasId, points, key, label, unit, decimals = 1) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas.getContext("2d");

    const width = canvas.clientWidth;
    const height = canvas.clientHeight;

    canvas.width = width;
    canvas.height = height;

    ctx.clearRect(0, 0, width, height);

    const padLeft = 56;
    const padRight = 14;
    const padTop = 30;
    const padBottom = 36;

    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    const clean = points
        .filter(p => p[key] !== null && p[key] !== undefined && !isNaN(Number(p[key])))
        .map(p => ({
            value: Number(p[key]),
            timestamp: p.timestamp
        }));

    // Background grid
    ctx.strokeStyle = "#d1d5db";
    ctx.lineWidth = 1;

    for (let i = 0; i <= 4; i++) {
        let y = padTop + (plotH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(width - padRight, y);
        ctx.stroke();
    }

    ctx.beginPath();
    ctx.moveTo(padLeft, padTop);
    ctx.lineTo(padLeft, padTop + plotH);
    ctx.lineTo(width - padRight, padTop + plotH);
    ctx.stroke();

    ctx.fillStyle = "#6b7280";
    ctx.font = "11px Arial";

    if (clean.length < 2) {
        ctx.fillText("Waiting for more data...", padLeft, padTop + 20);
        return;
    }

    const values = clean.map(p => p.value);
    let min = Math.min(...values);
    let max = Math.max(...values);

    // Add small padding so line does not touch top/bottom
    let range = max - min;

    if (range === 0) {
        range = 1;
        min = min - 0.5;
        max = max + 0.5;
    } else {
        const padding = range * 0.12;
        min = min - padding;
        max = max + padding;
        range = max - min;
    }

    // Y-axis labels
    for (let i = 0; i <= 4; i++) {
        let value = max - (range / 4) * i;
        let y = padTop + (plotH / 4) * i + 4;
        ctx.fillText(value.toFixed(decimals), 6, y);
    }

    // X-axis 24-hour time labels
    const labelCount = 4;

    for (let i = 0; i <= labelCount; i++) {
        let index = Math.round((clean.length - 1) * (i / labelCount));
        let x = padLeft + (plotW * i / labelCount);
        let t = formatTime24(clean[index].timestamp);

        ctx.fillText(t, x - 14, height - 10);
    }

    // Chart line
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    ctx.beginPath();

    clean.forEach((point, index) => {
        const x = padLeft + (index / (clean.length - 1)) * plotW;
        const y = padTop + plotH - ((point.value - min) / range) * plotH;

        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });

    ctx.stroke();

    // Title / Min Max
    ctx.fillStyle = "#111827";
    ctx.font = "13px Arial";
    ctx.fillText(
        label + "  Min: " + Math.min(...values).toFixed(decimals) + unit +
        "  Max: " + Math.max(...values).toFixed(decimals) + unit,
        padLeft,
        18
    );
}

async function requestPicoUpdate() {
    const pin = prompt("Enter Pico update PIN:");

    if (!pin) {
        alert("Update cancelled");
        return;
    }

    try {
        const response = await fetch("/api/request_update", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ pin: pin })
        });

        const data = await response.json();
        alert(data.message);
        loadData();
    } catch (error) {
        alert("Update request failed");
    }
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
        document.getElementById("update_status").innerHTML = data.update_status;

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

        drawChart("tempChart", data.history, "temperature", "Temperature", "°C", 1);
        drawChart("humChart", data.history, "humidity", "Humidity", "%", 1);
        drawChart("pressureChart", data.history, "pressure", "Pressure", " hPa", 1);

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


# =========================
# ROUTES
# =========================

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
        "update_status": pending_pico_update.get("message", "No update pending"),
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
@app.route("/api/data", methods=["POST"])
def api_update():
    global latest_data

    header_key = request.headers.get("X-API-Key", "")
    data = request.get_json(silent=True) or {}
    json_key = data.get("key", "")

    if header_key != API_KEY and json_key != API_KEY:
        return jsonify({
            "ok": False,
            "message": "Bad API key"
        }), 403

    timestamp = data.get("timestamp", now_string())
    temperature = safe_float(data.get("temperature"))
    humidity = safe_float(data.get("humidity"))
    pressure = safe_float(data.get("pressure"))
    status = data.get("status", "OK")
    version = data.get("version", "--")

    # Ignore bad NaN/null readings
    if temperature is None or humidity is None or pressure is None:
        latest_data["status"] = "SENSOR ERROR"
        latest_data["last_seen"] = now_string()
        latest_data["last_seen_epoch"] = time.time()

        return jsonify({
            "ok": False,
            "message": "Invalid sensor reading ignored"
        }), 400

    reading = {
        "timestamp": timestamp,
        "temperature": temperature,
        "humidity": humidity,
        "pressure": pressure,
        "status": status
    }

    history.append(reading)

    latest_data = {
        "timestamp": timestamp,
        "temperature": temperature,
        "humidity": humidity,
        "pressure": pressure,
        "status": status,
        "prediction": get_weather_prediction(),
        "version": version,
        "last_seen": now_string(),
        "last_seen_epoch": time.time()
    }

    return jsonify({
        "ok": True,
        "message": "Data received",
        "prediction": latest_data["prediction"]
    })


@app.route("/api/request_update", methods=["POST"])
def request_update():
    global pending_pico_update

    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", ""))

    if pin != UPDATE_PIN:
        return jsonify({
            "ok": False,
            "message": "Wrong update PIN"
        }), 403

    pending_pico_update["requested"] = True
    pending_pico_update["requested_at"] = now_string()
    pending_pico_update["message"] = "Pico update requested at " + now_string()

    return jsonify({
        "ok": True,
        "message": "Update request queued. Pico will install it next time it checks in."
    })


@app.route("/api/command", methods=["GET"])
def api_command():
    global pending_pico_update

    key = request.args.get("key", "")
    device_id = request.args.get("device_id", "pico")

    if key != API_KEY:
        return jsonify({
            "ok": False,
            "message": "Bad API key"
        }), 403

    if pending_pico_update["requested"]:
        pending_pico_update["requested"] = False
        pending_pico_update["message"] = "Update command sent to Pico at " + now_string()

        return jsonify({
            "ok": True,
            "device_id": device_id,
            "update": True,
            "message": "Update now"
        })

    return jsonify({
        "ok": True,
        "device_id": device_id,
        "update": False,
        "message": "No command"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
