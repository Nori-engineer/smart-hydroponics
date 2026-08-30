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

USB2_POWER_PIN = 13          # エアポンプ
TWELVEV_POWER_PIN = 14       # 12V水中ポンプ

SEND_INTERVAL = 3600         # 60分ごとに循環セットを実行
AIR_OFFSET = 300             # 水中ポンプの5分後にエアポンプを起動

OTA_CHECK_INTERVAL = 3600
HTTP_TIMEOUT = 15


# --- エアポンプ ---
def run_air_pump(pin_num=USB2_POWER_PIN, duration=10, wdt=None):
    print("エアポンプを起動します...")
    p = Pin(pin_num, Pin.OUT)
    p.value(1)
    for _ in range(duration):
        if wdt:
            wdt.feed()
        time.sleep(1)
    p.value(0)
    print("エアポンプを停止しました。")


# --- 12V水中ポンプ ---
def run_12v_pump(pin_num=TWELVEV_POWER_PIN, duration=10, wdt=None):
    print("12V 水中ポンプを起動します...")
    p = Pin(pin_num, Pin.OUT)
    p.value(1)
    for _ in range(duration):
        if wdt:
            wdt.feed()
        time.sleep(1)
    p.value(0)
    print("12V 水中ポンプを停止しました。")


# --- Wi-Fi ---
def connect_wifi(wdt=None):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(pm=0xa11154)
    except Exception:
        pass

    if not wlan.isconnected():
        print("Wi-Fiに再接続中...", end="")
        try:
            wlan.disconnect()
            time.sleep(1)
        except Exception:
            pass

        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 20
        while timeout > 0:
            if wdt:
                wdt.feed()
            status = wlan.status()
            if status == 3 or wlan.isconnected():
                break
            if status < 0:
                print(f"\nWi-Fi接続失敗 (ステータス: {status})")
                return False
            time.sleep(1)
            print(".", end="")
            timeout -= 1
        print()

    if wlan.isconnected():
        print("Wi-Fi接続完了 IP:", wlan.ifconfig()[0])
        return True
    else:
        print("Wi-Fi接続タイムアウト/失敗")
        return False


# --- OTA ---
def check_and_apply_ota(wdt=None):
    print("OTA更新をチェック中...")
    if wdt:
        wdt.feed()

    res = None
    try:
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


# --- スプレッドシート送信 ---
def send_to_spreadsheet(v_bus, current, power, wdt=None):
    if wdt:
        wdt.feed()

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


# --- メイン ---
def main():
    Pin(USB2_POWER_PIN, Pin.OUT).value(0)
    Pin(TWELVEV_POWER_PIN, Pin.OUT).value(0)

    connect_wifi()

    wdt = WDT(timeout=8300)
    wdt.feed()

    ina = None
    try:
        i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
        ina = INA219(i2c, addr=0x40)
    except Exception as e:
        print("INA219 初期化エラー:", e)

    check_and_apply_ota(wdt=wdt)
    wdt.feed()

    # 起動直後に初回実行されるよう初期値を設定
    current_now = time.time()
    last_send_time = current_now - SEND_INTERVAL
    last_air_time = None
    last_ota_time = current_now

    while True:
        wdt.feed()
        current_time = time.time()

        # --- 12V水中ポンプ（60分ごと） ---
        if current_time - last_send_time >= SEND_INTERVAL:
            # 送信前にWi-Fi接続状態を確認・再接続
            connect_wifi(wdt=wdt)

            run_12v_pump(TWELVEV_POWER_PIN, duration=10, wdt=wdt)
            last_send_time = current_time
            last_air_time = current_time + AIR_OFFSET   # エアポンプの予約 (5分後)

            # --- 計測＋送信 ---
            if ina:
                try:
                    v_bus = ina.get_bus_voltage()
                    current = ina.get_current()
                    power = v_bus * current
                    print(f"計測値 -> 電圧: {v_bus:.2f}V | 電流: {current:.1f}mA | 電力: {power:.1f}mW")
                    send_to_spreadsheet(v_bus, current, power, wdt=wdt)
                except Exception as e:
                    print("計測または送信失敗:", e)
            else:
                print("警告: INA219 が初期化されていないため、ダミー値(0.0)で送信テストを行います。")
                send_to_spreadsheet(0.0, 0.0, 0.0, wdt=wdt)

        # --- 水中ポンプの5分後にエアポンプ ---
        if last_air_time and current_time >= last_air_time:
            run_air_pump(USB2_POWER_PIN, duration=10, wdt=wdt)
            last_air_time = None

        # --- OTAチェック ---
        if current_time - last_ota_time >= OTA_CHECK_INTERVAL:
            connect_wifi(wdt=wdt)
            check_and_apply_ota(wdt=wdt)
            last_ota_time = current_time

        # --- 待機 ---
        for _ in range(10):
            wdt.feed()
            time.sleep(1)


if __name__ == "__main__":
    main()
