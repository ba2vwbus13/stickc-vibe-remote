# M5StickC Plus2 + Vibration HAT : Wi-Fi経由で振動させるHTTPサーバ
#
# ★このファイルは全機体で完全に共通です。機体ごとの設定は一切ありません。
#   機体の台帳(どのMACがどの名前か)はPC側の devices.py だけが持ちます。
#   そのため、機体を追加・改名しても既存機体への再書き込みは不要です。
#
# エンドポイント: /vibe?ms=N (N msだけ振動) / /hold?ms=N (押している間用) /
#                /off / /whoami
#
# デバイスはDHCPでIPを受け取り、/whoami で自分のMACを名乗るだけです。
# PC側の vibe.py がLANを探索して「MAC ↔ IP」の対応を見つけます。
#
# ★APは2.4GHzにしてください。ESP32は5GHzに対応していません。

import time
import network
import socket
import select
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

# /hold 用。PC側が「押している間」ずっと延命信号を送る前提で、
# 信号が途切れたら（PCが落ちた・Wi-Fiが切れた）必ず自力で止まる。
HOLD_DEFAULT_MS = 800
HOLD_MAX_MS = 2000     # 1回の延命で許す最大時間
POLL_MS = 20           # accept待ちの粒度＝ウォッチドッグの精度

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
    global _hold_until
    ms = max(0, min(int(ms), MAX_MS))
    _hold_until = 0          # ホールド中に /vibe が来たらホールドは打ち切る
    vibe.value(1)
    time.sleep_ms(ms)
    vibe.value(0)
    return ms


# ------------------------------------------------------------
# ホールド（押している間ずっと振動させる）
# ------------------------------------------------------------
# /vibe は指定時間ぶんブロックするので、途中で止められず長押しにも使えない。
# /hold は「ONにして期限だけ設定してすぐ返す」ので、PC側が短い間隔で
# 呼び直している限り振動が続き、/off で即座に止まる。
_hold_until = 0        # ticks_ms の期限。0 はホールドしていない状態


def hold_on(ms):
    """振動をONにして期限を延ばす。期限までに再度呼ばれなければ自動で止まる。

    ms=0 は「/hold に対応しているか」の問い合わせとして扱い、振動させない。
    PC側が起動時に方式を判定するのに使う（判定のたびに震えては困るため）。"""
    global _hold_until
    ms = max(0, min(int(ms), HOLD_MAX_MS))
    if ms == 0:
        hold_off()
        return 0
    vibe.value(1)
    _hold_until = time.ticks_add(time.ticks_ms(), ms) or 1
    return ms


def hold_off():
    global _hold_until
    _hold_until = 0
    vibe.value(0)


def hold_watchdog():
    """PC側が黙っても必ず止める。振動しっぱなしを防ぐ最後の砦。"""
    if _hold_until and time.ticks_diff(_hold_until, time.ticks_ms()) <= 0:
        hold_off()


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


def parse_ms(path, default=DEFAULT_MS):
    if "?" not in path:
        return default
    for kv in path.split("?", 1)[1].split("&"):
        if kv.startswith("ms="):
            try:
                return int(kv[3:])
            except ValueError:
                return default
    return default


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

    # accept でずっと寝ていると /hold のウォッチドッグを見に行けないので、
    # poll で POLL_MS ごとに起きて期限切れを確認する。
    poller = select.poll()
    poller.register(srv, select.POLLIN)

    while True:
        conn = None
        try:
            events = poller.poll(POLL_MS)
            hold_watchdog()
            if not events:
                continue

            conn, addr = srv.accept()
            req = conn.recv(512).decode("utf-8", "replace")
            path = req.split(" ", 2)[1] if req.startswith("GET ") else "/"

            if path.startswith("/vibe"):
                ms = buzz(parse_ms(path))
                body = "OK %d ms\n" % ms
                print("振動 %d ms  <- %s" % (ms, addr[0]))
            elif path.startswith("/hold"):
                # ONにして期限を延ばすだけ。ブロックしないので即座に返る
                ms = hold_on(parse_ms(path, HOLD_DEFAULT_MS))
                body = "HOLD %d ms\n" % ms
            elif path.startswith("/off"):
                hold_off()
                body = "OFF\n"
            elif path.startswith("/whoami"):
                # PC側の探索が使う。MACだけを名乗る（名前はPC側が決める）
                body = "%s\n" % MY_MAC
            else:
                body = ("StickC vibration server\n"
                        "  MAC: %s\n"
                        "  GET /vibe?ms=500   (max %d)\n"
                        "  GET /hold?ms=800   (max %d, 期限切れで自動停止 / ms=0は能力確認)\n"
                        "  GET /off\n"
                        "  GET /whoami\n" % (MY_MAC, MAX_MS, HOLD_MAX_MS))

            conn.send("HTTP/1.1 200 OK\r\n"
                      "Content-Type: text/plain; charset=utf-8\r\n"
                      "Connection: close\r\n\r\n")
            conn.send(body)
        except Exception as e:
            print("リクエスト処理エラー:", e)
            hold_off()   # 例外で振動しっぱなしにしない
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
