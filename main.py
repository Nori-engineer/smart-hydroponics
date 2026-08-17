import network
import requests
import time
from machine import Pin, I2C, reset, WDT
from ina219 import INA219

# --- 設定情報 ---
WIFI_SSID = "aterm-788953-g"
WIFI_PASSWORD = "9e69c0bce599a"

GAS_URL = "https://script.google.com/macros/s/AKfycbxOctbQIPjQPoUWXdr5x4OlJCWJCcs9L6SlbuVHtsyKR0epLcs5CkmhO1Si4L6lTHI/exec"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Nori-engineer/smart-hydroponics/refs/heads/main/main.py"

USB2_POWER_PIN = 13

SEND_INTERVAL = 3600       # 60分（3600秒）
OTA_CHECK_INTERVAL = 3600  # 1時間（3600秒）
HTTP_TIMEOUT = 15          # HTTP通信のタイムアウト（秒）


# --- 1. エアポンプ駆動 ---
def run_air_pump(pin_num=USB2_POWER_PIN, duration=10):
    print("エアポンプ(USB2)を起動します...")
    pump_pin = Pin(pin_num, Pin.OUT)
    pump_pin.value(1)
    time.sleep(duration)
    pump_pin.value(0)
    print("エアポンプ(USB2)を停止しました。")


# --- 2. Wi-Fi 接続（切断時の安全な再接続処理付き） ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Wi-Fiに再接続中...", end="")
        try:
            wlan.disconnect()
        except Exception:
            pass
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            print(".", end="")
            timeout -= 1
        print()

    if wlan.isconnected():
        print("Wi-Fi接続完了 IP:", wlan.ifconfig()[0])
        return True
    else:
        print("Wi-Fi接続失敗")
        return False


# --- 3. OTA更新処理（タイムアウト & ソケット安全解放追加） ---
def check_and_apply_ota():
    print("OTA更新をチェック中...")
    res = None
    try:
        # timeout を明示的に指定
        res = requests.get(GITHUB_RAW_URL, timeout=HTTP_TIMEOUT)
        if res.status_code == 200:
            new_code = res.text
            
            try:
                with open("main.py", "r") as f:
                    current_code = f.read()
            except OSError:
                current_code = ""

            if new_code != current_code and len(new_code) > 100:
                print("新しいコードを検出しました。更新中...")
                with open("main.py", "w") as f:
                    f.write(new_code)
                print("更新完了。再起動します。")
                time.sleep(2)
                reset()
            else:
                print("コードは最新状態です。")
        else:
            print("OTAチェック失敗 HTTP:", res.status_code)
    except Exception as e:
        print("OTAチェックエラー:", e)
    finally:
        if res:
            try:
                res.close()
            except Exception:
                pass


# --- 4. スプレッドシート送信処理（タイムアウト & try-finally追加） ---
def send_to_spreadsheet(v_bus, current, power):
    t = time.localtime()
    timestamp_str = f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

    payload = {
        "timestamp": timestamp_str,
        "voltage": round(v_bus, 2),
        "current": round(current, 1),
        "power": round(power, 1)
    }

    res = None
    try:
        # timeout を明示的に指定
        res = requests.post(GAS_URL, json=payload, timeout=HTTP_TIMEOUT)
        print("スプレッドシート送信結果:", res.status_code)
    except Exception as e:
        print("データ送信エラー:", e)
    finally:
        if res:
            try:
                res.close()
            except Exception:
                pass


# --- メイン処理 ---
def main():
    Pin(USB2_POWER_PIN, Pin.OUT).value(0)

    # Watchdog Timer の初期化（8.3秒以内に feed() されないとハードウェア再起動）
    # ※長時間の sleep を行う場合は毎ループ feed する必要があります
    wdt = WDT(timeout=8300)

    try:
        i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
        ina = INA219(i2c, addr=0x40)
    except Exception as e:
        print("INA219 初期化エラー:", e)

    connect_wifi()
    wdt.feed()

    check_and_apply_ota()
    wdt.feed()

    last_send_time = 0
    last_ota_time = time.time()

    while True:
        wdt.feed()  # ループごとにウォッチドッグタイマーをクリア
        current_time = time.time()

        # 定期送信処理
        if current_time - last_send_time >= SEND_INTERVAL:
            if not network.WLAN(network.STA_IF).isconnected():
                connect_wifi()
                wdt.feed()

            run_air_pump(USB2_POWER_PIN, duration=10)
            wdt.feed()

            try:
                v_bus = ina.get_bus_voltage()
                current = ina.get_current()
                power = ina.get_power()
                print(f"計測値 -> 電圧: {v_bus:.2f}V | 電流: {current:.1f}mA | 電力: {power:.1f}mW")
                send_to_spreadsheet(v_bus, current, power)
            except Exception as e:
                print("計測または送信失敗:", e)

            wdt.feed()
            last_send_time = current_time

        # 定期OTAチェック処理
        if current_time - last_ota_time >= OTA_CHECK_INTERVAL:
            check_and_apply_ota()
            wdt.feed()
            last_ota_time = current_time

        # 10秒待機（1秒ごとに分割してWDTをクリア）
        for _ in range(10):
            wdt.feed()
            time.sleep(1)

if __name__ == "__main__":
    main()
