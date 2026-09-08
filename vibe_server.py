# M5StickC Plus2 + Vibration HAT : Wi-Fi経由で振動させるHTTPサーバ
#
# ★このファイルは全機体で完全に共通です。機体ごとの設定は一切ありません。
#   機体の台帳(どのMACがどの名前か)はPC側の devices.py だけが持ちます。
#   そのため、機体を追加・改名しても既存機体への再書き込みは不要です。
#
# デバイスはDHCPでIPを受け取り、/whoami で自分のMACを名乗るだけです。
# PC側の vibe.py がLANを探索して「MAC ↔ IP」の対応を見つけます。
#
# ★APは2.4GHzにしてください。ESP32は5GHzに対応していません。

import time
import network
import socket
import binascii
from machine import Pin

# ------------------------------------------------------------
# 設定（全機体共通。ここだけ記入すれば全機体で使い回せます）
# ------------------------------------------------------------
# Wi-Fi情報は secrets.py に分離しています（Gitに含めないため）。
# secrets.py が無い場合はここの既定値が使われます。
try:
    from secrets import WIFI_SSID, WIFI_PASSWORD
except ImportError:
    WIFI_SSID = "ここにSSID"
    WIFI_PASSWORD = "ここにパスワード"

VIBE_PIN = 26          # 実機で特定済み（Vibration HAT のデータ線）
DEFAULT_MS = 300
MAX_MS = 3000          # 安全のための上限
PORT = 80

# Plus2 は GPIO4 をHIGHに保たないとバッテリー駆動時に電源が落ちます
try:
    Pin(4, Pin.OUT).value(1)
except Exception as e:
    print("power hold NG:", e)

vibe = Pin(VIBE_PIN, Pin.OUT)
vibe.value(0)

MY_MAC = "?"


def buzz(ms):
    """指定ミリ秒だけ振動させる。上限を超える値は MAX_MS に丸める。"""
    ms = max(0, min(int(ms), MAX_MS))
    vibe.value(1)
    time.sleep_ms(ms)
    vibe.value(0)
    return ms


def wifi_connect(timeout=20):
    """DHCPで接続する。固定IPは使わない（台帳を持たないため）。
    IPを固定したい場合は、AP側のDHCP予約(MACアドレス固定割当)を使ってください。
    そうすればデバイスのコードを変えずにIPを固定できます。"""
    global MY_MAC
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    raw = binascii.hexlify(wlan.config("mac")).decode()
    MY_MAC = ":".join(raw[i:i + 2] for i in range(0, 12, 2))
    print("MAC:", MY_MAC)

    if not wlan.isconnected():
        print("Wi-Fi接続中:", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        t0 = time.time()
        while not wlan.isconnected():
            if time.time() - t0 > timeout:
                raise OSError("Wi-Fi接続失敗: パスワード、APが2.4GHzか、電波を確認")
            time.sleep(0.5)
    return wlan.ifconfig()[0]


def parse_ms(path):
    if "?" not in path:
        return DEFAULT_MS
    for kv in path.split("?", 1)[1].split("&"):
        if kv.startswith("ms="):
            try:
                return int(kv[3:])
            except ValueError:
                return DEFAULT_MS
    return DEFAULT_MS


def main():
    ip = wifi_connect()
    print("接続しました。IP =", ip)

    try:
        import M5
        from M5 import Widgets
        M5.begin()
        # 台帳を持たないので名前は出せない。MACの下3桁とIPを表示する。
        Widgets.Label(MY_MAC[-8:], 4, 4, text_c=0xFFFFFF, bg_c=0x000000,
                      font=Widgets.FONTS.DejaVu18)
        Widgets.Label(ip, 4, 30, text_c=0x00FF00, bg_c=0x000000,
                      font=Widgets.FONTS.DejaVu18)
    except Exception as e:
        print("画面表示スキップ:", e)

    buzz(150)   # 起動確認

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(2)
    print("待受開始 port", PORT)

    while True:
        conn = None
        try:
            conn, addr = srv.accept()
            req = conn.recv(512).decode("utf-8", "replace")
            path = req.split(" ", 2)[1] if req.startswith("GET ") else "/"

            if path.startswith("/vibe"):
                ms = buzz(parse_ms(path))
                body = "OK %d ms\n" % ms
                print("振動 %d ms  <- %s" % (ms, addr[0]))
            elif path.startswith("/whoami"):
                # PC側の探索が使う。MACだけを名乗る（名前はPC側が決める）
                body = "%s\n" % MY_MAC
            else:
                body = ("StickC vibration server\n"
                        "  MAC: %s\n"
                        "  GET /vibe?ms=500   (max %d)\n"
                        "  GET /whoami\n" % (MY_MAC, MAX_MS))

            conn.send("HTTP/1.1 200 OK\r\n"
                      "Content-Type: text/plain; charset=utf-8\r\n"
                      "Connection: close\r\n\r\n")
            conn.send(body)
        except Exception as e:
            print("リクエスト処理エラー:", e)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
