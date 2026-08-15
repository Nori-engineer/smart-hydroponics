import network
import requests
import time
from machine import Pin, I2C, reset
from ina219 import INA219

# --- 設定情報 ---
WIFI_SSID = "aterm-788953-g"
WIFI_PASSWORD = "9e69c0bce599a"

# 1. Google Apps Script の Web アプリ URL
GAS_URL = "https://script.google.com/macros/s/AKfycbxOctbQIPjQPoUWXdr5x4OlJCWJCcs9L6SlbuVHtsyKR0epLcs5CkmhO1Si4L6lTHI/exec"

# 2. OTA用: GitHub の main.py Raw URL
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Nori-engineer/smart-hydroponics/refs/heads/main/main.py"

# 送信間隔（秒）
SEND_INTERVAL = 300  # 5分（300秒）ごとにデータ送信
OTA_CHECK_INTERVAL = 3600 # 1時間（3600秒）ごとにOTAチェック


# --- 1. Wi-Fi 接続 ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Wi-Fiに接続中...", end="")
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


# --- 2. OTA（GitHubコード自動更新）---
def check_and_apply_ota():
    print("OTA更新をチェック中...")
    try:
        res = requests.get(GITHUB_RAW_URL)
        if res.status_code == 200:
            new_code = res.text
            res.close()
            
            # 現在のファイルと内容を比較
            try:
                with open("main.py", "r") as f:
                    current_code = f.read()
            except OSError:
                current_code = ""

            # 変更があれば上書き保存してPicoを再起動
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
            res.close()
            print("OTAチェック失敗 HTTP:", res.status_code)
    except Exception as e:
        print("OTAチェックエラー:", e)


# --- 3. Google スプレッドシートデータ送信 ---
def send_to_spreadsheet(v_bus, current, power):
    # 日本時間（JST）の文字列生成（簡易表記）
    # ※NTPで時刻同期しない場合でも、GAS側で自動刻印されます
    t = time.localtime()
    timestamp_str = f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

    payload = {
        "timestamp": timestamp_str,
        "voltage": round(v_bus, 2),
        "current": round(current, 1),
        "power": round(power, 1)
    }

    try:
        # GASのリダイレクト(302)に対応してPOSTリクエストを送信
        res = requests.post(GAS_URL, json=payload)
        print("スプレッドシート送信結果:", res.status_code)
        res.close()
    except Exception as e:
        print("データ送信エラー:", e)


# --- メイン処理 ---
def main():
    # I2C・INA219の初期化
    i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
    ina = INA219(i2c, addr=0x40)

    connect_wifi()
    
    # 起動時に1回OTAチェックを実行
    check_and_apply_ota()

    last_send_time = 0
    last_ota_time = time.time()

    while True:
        current_time = time.time()

        # 定期送信処理
        if current_time - last_send_time >= SEND_INTERVAL:
            if not network.WLAN(network.STA_IF).isconnected():
                connect_wifi()

            v_bus = ina.get_bus_voltage()
            current = ina.get_current()
            power = ina.get_power()

            print(f"計測値 -> 電圧: {v_bus:.2f}V | 電流: {current:.1f}mA | 電力: {power:.1f}mW")
            send_to_spreadsheet(v_bus, current, power)
            last_send_time = current_time

        # 定期OTAチェック処理
        if current_time - last_ota_time >= OTA_CHECK_INTERVAL:
            check_and_apply_ota()
            last_ota_time = current_time

        time.sleep(10)

if __name__ == "__main__":
    main()

    main()
