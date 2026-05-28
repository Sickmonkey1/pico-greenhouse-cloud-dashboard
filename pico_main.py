# =========================
# NATHAN'S GREENHOUSE WEATHER STATION
# Pico W + BME280 + RTC + OLED + SD + Render Cloud + GitHub OTA
# Version: STABLE-SD-CLOUD-OTA-V1
# =========================

import network
import machine
import os
import gc
import math
import ujson
import urequests

from machine import Pin, SPI
from time import sleep, sleep_ms, ticks_ms, ticks_diff, localtime

import sdcard

from PiicoDev_BME280 import PiicoDev_BME280
from PiicoDev_SSD1306 import create_PiicoDev_SSD1306
from PiicoDev_RV3028 import PiicoDev_RV3028

try:
    import secrets
except:
    secrets = None


# =========================
# VERSION
# =========================

CURRENT_VERSION = "STABLE-SD-CLOUD-OTA-V1"


# =========================
# SETTINGS
# =========================

DEVICE_ID = "greenhouse-pico-1"

LOG_INTERVAL_MS = 60000
UPLOAD_INTERVAL_MS = 60000
COMMAND_CHECK_INTERVAL_MS = 60000

DAY_ROLLOVER_HOUR = 6

HUMIDITY_HIGH_WARNING = 90.0
TEMP_HIGH_WARNING = 35.0
TEMP_LOW_WARNING = 5.0

SD_MOUNT_PATH = "/sd"

SD_SPI_ID = 1
SD_SCK = 14
SD_MOSI = 15
SD_MISO = 12
SD_CS = 13

# Your Render site
DEFAULT_RENDER_BASE_URL = "https://pico-greenhouse-cloud-dashboard.onrender.com"

# Pico update files in your GitHub repo
GITHUB_MAIN_URL = "https://raw.githubusercontent.com/Sickmonkey1/pico-greenhouse-cloud-dashboard/main/pico_main.py"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/Sickmonkey1/pico-greenhouse-cloud-dashboard/main/pico_version.txt"


# =========================
# SECRETS
# =========================

def get_secret(name, default=None):
    try:
        return getattr(secrets, name)
    except:
        return default


WIFI_SSID = get_secret("WIFI_SSID", "")
WIFI_PASSWORD = get_secret("WIFI_PASSWORD", "")
PICO_API_KEY = get_secret("PICO_API_KEY", "")
RENDER_BASE_URL = get_secret("RENDER_BASE_URL", DEFAULT_RENDER_BASE_URL)

CLOUD_UPDATE_URL = RENDER_BASE_URL.rstrip("/") + "/api/update"
COMMAND_URL = RENDER_BASE_URL.rstrip("/") + "/api/command"


# =========================
# GLOBALS
# =========================

bme = None
oled = None
rtc = None
sd_ok = False
wifi_ok = False

latest_temperature = None
latest_pressure = None
latest_humidity = None
latest_status = "STARTING"
latest_prediction = "Collecting weather trend"

temp_min = None
temp_max = None
hum_min = None
hum_max = None
pressure_min = None
pressure_max = None

pressure_history = []
humidity_history = []
temperature_history = []
MAX_LOCAL_HISTORY = 180

last_log_ms = 0
last_upload_ms = 0
last_command_check_ms = 0


# =========================
# BASIC HELPERS
# =========================

def is_valid_number(value):
    try:
        value = float(value)

        if math.isnan(value):
            return False

        if math.isinf(value):
            return False

        return True
    except:
        return False


def safe_round(value, decimals=2):
    if not is_valid_number(value):
        return None

    return round(float(value), decimals)


def add_history(history_list, value):
    if is_valid_number(value):
        history_list.append(float(value))

    while len(history_list) > MAX_LOCAL_HISTORY:
        history_list.pop(0)


def update_min_max():
    global temp_min, temp_max, hum_min, hum_max, pressure_min, pressure_max

    if is_valid_number(latest_temperature):
        t = float(latest_temperature)
        temp_min = t if temp_min is None else min(temp_min, t)
        temp_max = t if temp_max is None else max(temp_max, t)

    if is_valid_number(latest_humidity):
        h = float(latest_humidity)
        hum_min = h if hum_min is None else min(hum_min, h)
        hum_max = h if hum_max is None else max(hum_max, h)

    if is_valid_number(latest_pressure):
        p = float(latest_pressure)
        pressure_min = p if pressure_min is None else min(pressure_min, p)
        pressure_max = p if pressure_max is None else max(pressure_max, p)


def get_status():
    if not is_valid_number(latest_temperature):
        return "SENSOR ERROR"

    if not is_valid_number(latest_humidity):
        return "SENSOR ERROR"

    if not is_valid_number(latest_pressure):
        return "SENSOR ERROR"

    if latest_humidity >= HUMIDITY_HIGH_WARNING:
        return "HUMIDITY HIGH"

    if latest_temperature >= TEMP_HIGH_WARNING:
        return "TEMP HIGH"

    if latest_temperature <= TEMP_LOW_WARNING:
        return "TEMP LOW"

    return "OK"


def get_change(values, count):
    if len(values) < 2:
        return None

    recent = values[-count:]

    if len(recent) < 2:
        return None

    return recent[-1] - recent[0]


def update_weather_prediction():
    global latest_prediction

    if len(pressure_history) < 10:
        latest_prediction = "Collecting weather trend"
        return latest_prediction

    pressure_30 = get_change(pressure_history, 30)
    pressure_60 = get_change(pressure_history, 60)
    humidity_30 = get_change(humidity_history, 30)
    temp_30 = get_change(temperature_history, 30)

    if pressure_30 is None:
        latest_prediction = "Collecting weather trend"
        return latest_prediction

    if pressure_30 <= -1.0 and humidity_30 is not None and humidity_30 >= 3:
        latest_prediction = "Pressure falling + humidity rising - rain/storm possible"

    elif pressure_30 <= -1.5:
        latest_prediction = "Pressure falling quickly - unsettled weather possible"

    elif pressure_60 is not None and pressure_60 <= -2.0:
        latest_prediction = "Pressure falling over the hour - rain possible"

    elif pressure_30 >= 1.0 and humidity_30 is not None and humidity_30 <= -2:
        latest_prediction = "Pressure rising + humidity dropping - clearing/improving"

    elif pressure_30 >= 1.5:
        latest_prediction = "Pressure rising - weather improving"

    elif is_valid_number(latest_humidity) and latest_humidity >= 90:
        latest_prediction = "Very humid - damp/rainy conditions possible"

    elif is_valid_number(latest_humidity) and latest_humidity >= 85:
        latest_prediction = "Humidity high - moisture in the air"

    elif temp_30 is not None and humidity_30 is not None and temp_30 <= -1.0 and humidity_30 >= 2:
        latest_prediction = "Cooling with humidity rising - rain nearby possible"

    else:
        latest_prediction = "Pressure stable"

    return latest_prediction


# =========================
# OLED
# =========================

def oled_message(line1="", line2="", line3="", line4=""):
    try:
        if oled is None:
            return

        oled.fill(0)
        oled.text(str(line1)[:16], 0, 0, 1)
        oled.text(str(line2)[:16], 0, 16, 1)
        oled.text(str(line3)[:16], 0, 32, 1)
        oled.text(str(line4)[:16], 0, 48, 1)
        oled.show()
    except:
        pass


def oled_live():
    if not is_valid_number(latest_temperature):
        oled_message("Sensor Error", "Check BME280", "or cable", "")
        return

    oled_message(
        "Greenhouse",
        "T: {:.1f} C".format(latest_temperature),
        "H: {:.1f} %".format(latest_humidity),
        "P: {:.1f} hPa".format(latest_pressure)
    )


# =========================
# RTC TIME
# =========================

def init_rtc():
    global rtc

    try:
        rtc = PiicoDev_RV3028()
        print("RTC ready")
    except Exception as e:
        rtc = None
        print("RTC error:", e)


def parse_datetime_tuple(dt):
    try:
        # Common MicroPython style:
        # (year, month, day, weekday, hour, minute, second, subseconds)
        if len(dt) >= 8:
            year = dt[0]
            month = dt[1]
            day = dt[2]
            hour = dt[4]
            minute = dt[5]
            second = dt[6]
            return year, month, day, hour, minute, second

        # Some RTC libraries:
        # (year, month, day, hour, minute, second)
        if len(dt) >= 6:
            year = dt[0]
            month = dt[1]
            day = dt[2]
            hour = dt[3]
            minute = dt[4]
            second = dt[5]
            return year, month, day, hour, minute, second

    except:
        pass

    return None


def now_tuple():
    try:
        if rtc is not None:
            dt = rtc.datetime()
            parsed = parse_datetime_tuple(dt)

            if parsed is not None:
                year, month, day, hour, minute, second = parsed

                if year >= 2024:
                    return parsed
    except:
        pass

    try:
        lt = localtime()
        return lt[0], lt[1], lt[2], lt[3], lt[4], lt[5]
    except:
        return 2000, 1, 1, 0, 0, 0


def timestamp_string():
    year, month, day, hour, minute, second = now_tuple()

    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        year, month, day, hour, minute, second
    )


def is_leap_year(year):
    if year % 400 == 0:
        return True

    if year % 100 == 0:
        return False

    return year % 4 == 0


def days_in_month(year, month):
    if month in [1, 3, 5, 7, 8, 10, 12]:
        return 31

    if month in [4, 6, 9, 11]:
        return 30

    if is_leap_year(year):
        return 29

    return 28


def previous_date(year, month, day):
    day -= 1

    if day >= 1:
        return year, month, day

    month -= 1

    if month >= 1:
        return year, month, days_in_month(year, month)

    year -= 1
    month = 12
    day = 31

    return year, month, day


def log_filename():
    year, month, day, hour, minute, second = now_tuple()

    if hour < DAY_ROLLOVER_HOUR:
        year, month, day = previous_date(year, month, day)

    return "{}/{:04d}-{:02d}-{:02d}.csv".format(SD_MOUNT_PATH, year, month, day)


# =========================
# HARDWARE INIT
# =========================

def init_oled():
    global oled

    try:
        oled = create_PiicoDev_SSD1306()
        oled_message("Greenhouse", "Starting...", "", "")
        print("OLED ready")
    except Exception as e:
        oled = None
        print("OLED error:", e)


def init_bme():
    global bme

    try:
        bme = PiicoDev_BME280()
        print("BME280 ready")
    except Exception as e:
        bme = None
        print("BME280 error:", e)


def init_sd():
    global sd_ok

    try:
        spi = SPI(
            SD_SPI_ID,
            baudrate=400000,
            polarity=0,
            phase=0,
            sck=Pin(SD_SCK),
            mosi=Pin(SD_MOSI),
            miso=Pin(SD_MISO)
        )

        cs = Pin(SD_CS, Pin.OUT)
        sd = sdcard.SDCard(spi, cs)

        try:
            os.mount(sd, SD_MOUNT_PATH)
        except OSError:
            pass

        print("SD mounted at", SD_MOUNT_PATH)
        print("SD files:", os.listdir(SD_MOUNT_PATH))

        sd_ok = True
        return True

    except Exception as e:
        print("SD card error:", e)
        sd_ok = False
        return False


def connect_wifi():
    global wifi_ok

    if WIFI_SSID == "" or WIFI_PASSWORD == "":
        print("WiFi secrets missing")
        wifi_ok = False
        return False

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting WiFi...")
        oled_message("WiFi", "Connecting...", "", "")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)

        start = ticks_ms()

        while not wlan.isconnected():
            if ticks_diff(ticks_ms(), start) > 20000:
                print("WiFi failed")
                oled_message("WiFi failed", "Still logging SD", "", "")
                wifi_ok = False
                return False

            sleep_ms(500)

    ip = wlan.ifconfig()[0]
    print("WiFi connected:", ip)
    oled_message("WiFi connected", ip, "", "")
    wifi_ok = True
    return True


# =========================
# SENSOR
# =========================

def read_sensor():
    global latest_temperature, latest_pressure, latest_humidity, latest_status

    if bme is None:
        latest_status = "SENSOR ERROR"
        return False

    try:
        temp_c, pressure_raw, hum_rh = bme.values()

        # Some BME280 libraries return Pa, some return hPa.
        pressure_hpa = float(pressure_raw)

        if pressure_hpa > 2000:
            pressure_hpa = pressure_hpa / 100.0

        temp_c = float(temp_c)
        hum_rh = float(hum_rh)

        if not is_valid_number(temp_c) or not is_valid_number(pressure_hpa) or not is_valid_number(hum_rh):
            latest_status = "SENSOR ERROR"
            return False

        latest_temperature = safe_round(temp_c, 2)
        latest_pressure = safe_round(pressure_hpa, 2)
        latest_humidity = safe_round(hum_rh, 2)

        add_history(temperature_history, latest_temperature)
        add_history(pressure_history, latest_pressure)
        add_history(humidity_history, latest_humidity)

        update_min_max()
        latest_status = get_status()
        update_weather_prediction()

        return True

    except Exception as e:
        print("Sensor read error:", e)
        latest_status = "SENSOR ERROR"
        return False


# =========================
# SD LOGGING
# =========================

def ensure_log_header(filename):
    try:
        try:
            os.stat(filename)
            return
        except:
            pass

        with open(filename, "w") as f:
            f.write("Timestamp,TemperatureC,PressurehPa,HumidityRH,TempMin,TempMax,HumMin,HumMax,PressureMin,PressureMax,Status,Prediction\n")
            f.flush()

    except Exception as e:
        print("Header write error:", e)


def log_to_sd():
    if not sd_ok:
        print("SD not ready - no log")
        return False

    if latest_status == "SENSOR ERROR":
        print("Sensor error - skipped SD log")
        return False

    try:
        filename = log_filename()
        ensure_log_header(filename)

        line = "{},{},{},{},{},{},{},{},{},{},{},{}\n".format(
            timestamp_string(),
            latest_temperature,
            latest_pressure,
            latest_humidity,
            temp_min,
            temp_max,
            hum_min,
            hum_max,
            pressure_min,
            pressure_max,
            latest_status,
            latest_prediction
        )

        with open(filename, "a") as f:
            f.write(line)
            f.flush()

        print(line.strip())
        return True

    except Exception as e:
        print("SD log error:", e)
        return False


# =========================
# CLOUD UPLOAD
# =========================

def upload_to_cloud():
    if not wifi_ok:
        return False

    if latest_status == "SENSOR ERROR":
        print("Sensor error - skipped cloud upload")
        return False

    response = None

    try:
        payload = {
            "timestamp": timestamp_string(),
            "temperature": latest_temperature,
            "humidity": latest_humidity,
            "pressure": latest_pressure,
            "status": latest_status,
            "prediction": latest_prediction,
            "version": CURRENT_VERSION,
            "device_id": DEVICE_ID
        }

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": PICO_API_KEY
        }

        response = urequests.post(
            CLOUD_UPDATE_URL,
            data=ujson.dumps(payload),
            headers=headers
        )

        print("Cloud upload:", response.status_code)

        try:
            response.close()
        except:
            pass

        gc.collect()
        return True

    except Exception as e:
        print("Cloud upload error:", e)

        try:
            if response:
                response.close()
        except:
            pass

        gc.collect()
        return False


# =========================
# OTA UPDATE
# =========================

def ota_file_exists(path):
    try:
        os.stat(path)
        return True
    except:
        return False


def ota_remove_if_exists(path):
    try:
        if ota_file_exists(path):
            os.remove(path)
    except Exception as e:
        print("OTA remove error:", path, e)


def ota_copy_file(source, destination):
    with open(source, "rb") as src:
        with open(destination, "wb") as dst:
            while True:
                chunk = src.read(512)

                if not chunk:
                    break

                dst.write(chunk)


def ota_get_text(url):
    response = None

    try:
        gc.collect()
        response = urequests.get(url)

        if response.status_code != 200:
            print("OTA HTTP error:", response.status_code)
            response.close()
            return None

        text = response.text
        response.close()
        gc.collect()

        return text

    except Exception as e:
        print("OTA get text error:", e)

        try:
            if response:
                response.close()
        except:
            pass

        gc.collect()
        return None


def ota_download_file(url, destination):
    response = None

    try:
        gc.collect()
        response = urequests.get(url)

        if response.status_code != 200:
            print("OTA download HTTP error:", response.status_code)
            response.close()
            return False

        ota_remove_if_exists(destination)

        with open(destination, "wb") as f:
            while True:
                chunk = response.raw.read(512)

                if not chunk:
                    break

                f.write(chunk)

            f.flush()

        response.close()
        gc.collect()
        return True

    except Exception as e:
        print("OTA download error:", e)

        try:
            if response:
                response.close()
        except:
            pass

        gc.collect()
        return False


def ota_file_contains(path, text):
    try:
        with open(path, "r") as f:
            while True:
                chunk = f.read(512)

                if not chunk:
                    break

                if text in chunk:
                    return True

        return False

    except Exception as e:
        print("OTA validation read error:", e)
        return False


def ota_install_latest():
    print("OTA: checking GitHub version")
    oled_message("OTA Update", "Checking GitHub", "", "")

    latest_version = ota_get_text(GITHUB_VERSION_URL)

    if latest_version is None:
        print("OTA: could not read version")
        oled_message("OTA failed", "No version file", "", "")
        return False

    latest_version = latest_version.strip()

    print("Current version:", CURRENT_VERSION)
    print("Latest version:", latest_version)

    if latest_version == CURRENT_VERSION:
        print("OTA: already up to date")
        oled_message("OTA", "Already latest", CURRENT_VERSION[-8:], "")
        return True

    oled_message("OTA Update", "Downloading...", latest_version[-16:], "")

    if not ota_download_file(GITHUB_MAIN_URL, "/main_new.py"):
        print("OTA: download failed")
        oled_message("OTA failed", "Download error", "", "")
        return False

    if not ota_file_exists("/main_new.py"):
        print("OTA: new file missing")
        oled_message("OTA failed", "File missing", "", "")
        return False

    if not ota_file_contains("/main_new.py", "CURRENT_VERSION"):
        print("OTA: validation failed - no CURRENT_VERSION")
        oled_message("OTA failed", "Bad file", "", "")
        ota_remove_if_exists("/main_new.py")
        return False

    if not ota_file_contains("/main_new.py", latest_version):
        print("OTA: validation failed - version text missing")
        oled_message("OTA failed", "Version mismatch", "", "")
        ota_remove_if_exists("/main_new.py")
        return False

    print("OTA: backing up main.py")
    oled_message("OTA Update", "Backing up...", "", "")

    try:
        ota_remove_if_exists("/main_backup.py")

        if ota_file_exists("/main.py"):
            ota_copy_file("/main.py", "/main_backup.py")

    except Exception as e:
        print("OTA backup failed:", e)
        oled_message("OTA failed", "Backup failed", "", "")
        ota_remove_if_exists("/main_new.py")
        return False

    print("OTA: replacing main.py")
    oled_message("OTA Update", "Installing...", "", "")

    try:
        ota_remove_if_exists("/main.py")
        os.rename("/main_new.py", "/main.py")

        print("OTA: install complete")
        oled_message("OTA Complete", "Rebooting...", latest_version[-16:], "")
        sleep_ms(2000)
        machine.reset()

    except Exception as e:
        print("OTA install failed:", e)

        try:
            if ota_file_exists("/main_backup.py"):
                ota_remove_if_exists("/main.py")
                ota_copy_file("/main_backup.py", "/main.py")
                print("OTA: backup restored")
                oled_message("OTA failed", "Backup restored", "", "")
        except Exception as restore_error:
            print("OTA restore failed:", restore_error)
            oled_message("OTA failed", "Restore failed", "", "")

        return False


def check_render_command():
    if not wifi_ok:
        return

    response = None

    try:
        url = COMMAND_URL + "?key=" + PICO_API_KEY + "&device_id=" + DEVICE_ID

        response = urequests.get(url)

        if response.status_code != 200:
            print("Command check HTTP error:", response.status_code)
            response.close()
            return

        data = response.json()
        response.close()

        if data.get("update") == True:
            print("Command received: OTA UPDATE")
            ota_install_latest()
        else:
            print("Command: no update")

    except Exception as e:
        print("Command check error:", e)

        try:
            if response:
                response.close()
        except:
            pass

    gc.collect()


# =========================
# STARTUP
# =========================

def startup():
    global last_log_ms, last_upload_ms, last_command_check_ms

    print("")
    print("==============================")
    print("Nathan's Greenhouse Station")
    print("Version:", CURRENT_VERSION)
    print("==============================")

    init_oled()
    oled_message("Greenhouse", "Booting...", CURRENT_VERSION[-16:], "")

    init_bme()
    init_rtc()
    init_sd()
    connect_wifi()

    read_sensor()
    oled_live()
    log_to_sd()
    upload_to_cloud()
    check_render_command()

    now = ticks_ms()
    last_log_ms = now
    last_upload_ms = now
    last_command_check_ms = now

    print("Startup complete")


# =========================
# MAIN LOOP
# =========================

startup()

while True:
    try:
        now = ticks_ms()

        sensor_ok = read_sensor()
        oled_live()

        if ticks_diff(now, last_log_ms) >= LOG_INTERVAL_MS:
            if sensor_ok:
                log_to_sd()

            last_log_ms = now

        if ticks_diff(now, last_upload_ms) >= UPLOAD_INTERVAL_MS:
            if sensor_ok:
                upload_to_cloud()

            last_upload_ms = now

        if ticks_diff(now, last_command_check_ms) >= COMMAND_CHECK_INTERVAL_MS:
            check_render_command()
            last_command_check_ms = now

        gc.collect()
        sleep_ms(1000)

    except Exception as e:
        print("Main loop error:", e)
        oled_message("Main Error", str(e)[:16], "Restarting loop", "")
        sleep_ms(3000)
