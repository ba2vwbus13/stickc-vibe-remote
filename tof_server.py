# M5Go + ToFユニット(VL53L0X) : 前方の障害物を検知して StickC を振動させる
#
# ★このファイルは M5Go に書き込みます（StickC 側は vibe_server.py）。
#
# 配線: ToFユニットを Port A（本体上部の赤いGroveコネクタ、I2C）に接続
#       Port A = SDA:G21 / SCL:G22、ToFのI2Cアドレスは 0x29
#
# 実測で確定した仕様（2026-09-09）:
#   ・get_distance() は cm 単位の float を返す
#   ・測定できないときは -0.1 を返す（「遠すぎる」と「エラー」は区別できない）
#   ・実用限界は約1m。1.5mは設定を変えても測定できなかった
#   ・既定設定では1mで2割が失敗し ±14cm ばらつく。下記の調整が必須

import time
import network
import socket

import M5
from M5 import Widgets
from hardware import I2C, Pin
from unit import ToFUnit

try:
    from secrets import WIFI_SSID, WIFI_PASSWORD
except ImportError:
    WIFI_SSID = "ここにSSID"
    WIFI_PASSWORD = "ここにパスワード"

# ------------------------------------------------------------
# 設定
# ------------------------------------------------------------
# 振動させる StickC。IPは書きません。
# 起動時にUDPブロードキャストで探索し、応答したStickCのIPを自動で使います。
# DHCPでIPが変わっても追従するので、AP側のDHCP予約は不要です。
#
# 特定の機体だけを鳴らしたい場合は、そのMACアドレスを書いてください。
# 空文字なら最初に応答した1台を使います。
VIBE_MAC = ""                # 例: "10:06:1c:27:c4:74"
VIBE_IP = ""                 # 探索結果が入ります。手動で固定したい場合はここに直接IPを書く
VIBE_PORT = 80               # StickCは80番。動作確認で別サーバを使うときだけ変える
DISCOVERY_PORT = 9999        # StickC側の探索応答ポート
DISCOVERY_QUERY = b"YUISHIRUBE?"
DISCOVERY_WAIT_S = 1.5       # 応答を待つ秒数
VIBE_MS_NEAR = 600           # 近い(WARN_NEAR_CM以内)ときの振動時間
VIBE_MS_FAR = 200            # 警告圏内だが遠いときの振動時間

WARN_CM = 80.0               # この距離以下で警告（実用限界1mの内側に取る）
WARN_NEAR_CM = 40.0          # この距離以下は「すぐ目の前」として強く振動
NEED_HITS = 2                # 直近この回数連続で条件成立したら発報（誤検知よけ）
COOLDOWN_S = 2.0             # 発報直後の最低沈黙時間（連打防止）

# 発報の繰り返し方を選ぶ。
#   True  : 障害物が警告圏内にある間、COOLDOWN_S ごとに鳴らし続ける
#   False : 一度鳴ったら CLEAR_CM より離れるまで黙る
# 「まだそこにある」ことを知らせ続けたいなら True、
# 置きっぱなしの物に鳴り続けるのが煩わしいなら False。
REPEAT_WHILE_NEAR = True

# 復帰の判定は WARN_CM より少し遠い CLEAR_CM で行う（ヒステリシス）。
# 同じ値で判定すると、境界付近のばらつきで鳴ったり止まったりを繰り返す。
CLEAR_CM = 95.0              # この距離より遠ざかったら再び発報できる状態に戻す
NEED_CLEAR = 2               # 復帰にもこの回数の連続が必要

# 測定時間。実測では 34,433us(既定) → 300,000us でばらつきが 27cm → 2cm に改善。
# 大きくすると精度は上がるが1回あたり約0.3秒かかる（応答が遅くなる）。
TIMING_BUDGET_US = 300000
SIGNAL_RATE_LIMIT = 0.05     # 下げると遠距離が安定する。1mで効果を確認済み


# ------------------------------------------------------------
# 初期化
# ------------------------------------------------------------
M5.begin()

Widgets.fillScreen(0x000000)
title_label = Widgets.Label("ToF Obstacle", 10, 8, text_c=0xFFFFFF, bg_c=0x000000,
                            font=Widgets.FONTS.DejaVu18)
dist_label = Widgets.Label("---", 10, 50, text_c=0x00FF00, bg_c=0x000000,
                           font=Widgets.FONTS.DejaVu40)
state_label = Widgets.Label("starting", 10, 120, text_c=0xFFFFFF, bg_c=0x000000,
                            font=Widgets.FONTS.DejaVu18)
net_label = Widgets.Label("", 10, 160, text_c=0x888888, bg_c=0x000000,
                          font=Widgets.FONTS.DejaVu18)

_my_ip = None                # 自分のIP（探索でサブネットを求めるのに使う）

i2c0 = I2C(0, sda=Pin(21), scl=Pin(22), freq=100000)
tof = ToFUnit(i2c=i2c0)          # ENVユニットと同じく i2c= で渡す（port= は不可）
tof.set_measurement_timing_budget(TIMING_BUDGET_US)
tof.set_signal_rate_limit(SIGNAL_RATE_LIMIT)


def wifi_connect(timeout=15):
    """Wi-Fiに繋ぐ。失敗しても致命傷にせず、画面表示だけは動かす。"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        t0 = time.time()
        while not wlan.isconnected():
            if time.time() - t0 > timeout:
                print("Wi-Fi接続失敗（振動通知なしで続行）")
                return None
            time.sleep(0.5)
    return wlan.ifconfig()[0]


def discover_stick(my_ip):
    """UDPブロードキャストでStickCを探し、IPを返す。見つからなければ None。

    宛先は 255.255.255.255 ではなく **サブネットブロードキャスト**（例 192.168.11.255）
    を使う。255.255.255.255 は環境によってルーティングされず、実際に macOS からは
    届かないことを実測で確認している。"""
    bcast = my_ip.rsplit(".", 1)[0] + ".255"
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sk.settimeout(0.3)
        sk.sendto(DISCOVERY_QUERY, (bcast, DISCOVERY_PORT))
        t0 = time.time()
        first = None
        while time.time() - t0 < DISCOVERY_WAIT_S:
            try:
                data, sender = sk.recvfrom(128)
            except Exception:
                continue
            txt = data.decode("utf-8", "replace").strip()
            if not txt.startswith("YUISHIRUBE "):
                continue
            parts = txt.split()
            mac = parts[1]
            ip = parts[2] if len(parts) > 2 else sender[0]
            print("  探索応答: %s -> %s" % (mac, ip))
            if VIBE_MAC and mac.lower() == VIBE_MAC.lower():
                sk.close()
                return ip                      # 指定機体が見つかった
            if first is None:
                first = ip
        sk.close()
        return None if VIBE_MAC else first
    except Exception as e:
        print("探索エラー:", e)
        return None


def notify_vibe(ms):
    """StickC に振動を指示する。届かなくても本体の動作は止めない。
    失敗したら1度だけ再探索する（StickCが再起動してIPが変わった場合に追従）。"""
    global VIBE_IP
    if not VIBE_IP:
        return False
    if _send_vibe(ms):
        return True
    print("再探索します")
    ip = discover_stick(_my_ip) if _my_ip else None
    if ip and ip != VIBE_IP:
        VIBE_IP = ip
        print("StickCのIPが変わりました ->", VIBE_IP)
        return _send_vibe(ms)
    return False


def _send_vibe(ms):
    try:
        addr = socket.getaddrinfo(VIBE_IP, VIBE_PORT)[0][-1]
        sk = socket.socket()
        sk.settimeout(1.5)
        sk.connect(addr)
        sk.send("GET /vibe?ms=%d HTTP/1.0\r\nHost: %s\r\n\r\n" % (ms, VIBE_IP))
        sk.recv(64)
        sk.close()
        return True
    except Exception as e:
        print("振動通知に失敗:", e)
        return False


def read_distance():
    """距離を cm で返す。測定できなければ None。
    -0.1 は「範囲外またはエラー」で、負値をそのまま比較すると
    「すぐ目の前」と誤判定するため、ここで確実に潰しておく。"""
    try:
        d = tof.get_distance()
    except Exception as e:
        print("読み取りエラー:", e)
        return None
    if d is None or d <= 0:
        return None
    return d


# ------------------------------------------------------------
# メインループ
# ------------------------------------------------------------
def main():
    global VIBE_IP, _my_ip
    _my_ip = wifi_connect()
    if _my_ip:
        if not VIBE_IP:
            print("StickCを探索中...")
            found = discover_stick(_my_ip)
            if found:
                VIBE_IP = found
                print("StickC を発見:", VIBE_IP)
            else:
                print("StickCが見つかりません（画面表示のみで続行）")
        net_label.setText("-> %s" % VIBE_IP if VIBE_IP else "no stick")
    else:
        net_label.setText("wifi NG")

    hits = 0            # 警告圏内が連続した回数
    clears = 0          # 圏外が連続した回数
    fired = False       # 発報済みで、離れるまで黙っている状態か
    last_fire = 0.0

    while True:
        d = read_distance()

        # --- 圏外（離れた or 測定不能）の判定 ---
        # 測定不能(-0.1)は「1m以内に何も無い」ことが多いので圏外扱いにする。
        # ただし1回で決めつけず NEED_CLEAR 回の連続を求める。
        if d is None or d > CLEAR_CM:
            clears += 1
            hits = 0
            if clears >= NEED_CLEAR and fired:
                fired = False       # 離れたので再び発報できる状態に戻す
                print("復帰: 再発報できる状態に戻りました")
            if d is None:
                dist_label.setColor(0x666666, 0x000000)
                dist_label.setText("--- cm")
                state_label.setText("no echo")
            else:
                dist_label.setColor(0x00FF00, 0x000000)
                dist_label.setText("%.0f cm" % d)
                state_label.setText("clear")

        # --- 警告圏内 ---
        elif d <= WARN_CM:
            clears = 0
            hits += 1
            near = d <= WARN_NEAR_CM
            dist_label.setColor(0xFF0000 if near else 0xFFAA00, 0x000000)
            dist_label.setText("%.0f cm" % d)
            now = time.time()
            if fired and not REPEAT_WHILE_NEAR:
                state_label.setText("held")     # 発報済み。離れるまで黙る
            elif hits >= NEED_HITS and (now - last_fire) >= COOLDOWN_S:
                ms = VIBE_MS_NEAR if near else VIBE_MS_FAR
                ok = notify_vibe(ms)
                last_fire = now
                fired = True
                print("発報 %.0fcm -> %dms %s" % (d, ms, "OK" if ok else "(通知なし)"))
                state_label.setText("FIRE %dms" % ms)
            else:
                state_label.setText("NEAR" if near else "warn")

        # --- WARN_CM と CLEAR_CM の間（ヒステリシス帯）---
        else:
            clears = 0
            hits = 0
            dist_label.setColor(0xFFFF00, 0x000000)
            dist_label.setText("%.0f cm" % d)
            state_label.setText("idle" if REPEAT_WHILE_NEAR or not fired else "held")

        M5.update()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
