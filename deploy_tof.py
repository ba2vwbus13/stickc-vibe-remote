#!/usr/bin/env python3
"""M5Go に tof_server.py（障害物センサ）を書き込む。

    python3 deploy_tof.py           # 書き込んで再起動、起動ログを表示
    python3 deploy_tof.py --run     # 書き込まずRAM実行だけ試す（20秒）
    python3 deploy_tof.py --list    # 接続中の機器を判別して一覧表示
    python3 deploy_tof.py --port /dev/cu.usbserial-XXXX   # ポートを明示指定

StickC 用は deploy.py。こちらは M5Go（Core）専用。

複数のM5Stack機器が繋がっていても、各ポートの `os.uname().machine` を読んで
M5Go だけを選ぶ。ただし**判別のために各機器へ接続するので、StickC等は
その時点でリセットされる**（動作中の実験を止めたくないときは --port で指定すること）。
"""
import argparse
import glob
import os
import sys
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_MAIN = os.path.join(HERE, "tof_server.py")
SRC_SECRETS = os.path.join(HERE, "secrets.py")

# os.uname().machine に含まれる文字列で機種を見分ける
M5GO_MARKER = "M5STACK BASIC"


def drain(s, sec):
    t = time.time(); b = b""
    while time.time() - t < sec:
        b += s.read(4096)
    return b


def enter_repl(s, tries=35):
    for _ in range(tries):
        s.write(b"\x02\r\x03\x03")
        if drain(s, 0.5).rstrip().endswith(b">>>"):
            return True
    return False


def raw_exec(s, script_bytes, wait):
    s.write(b"\x01")
    if b"raw REPL" not in drain(s, 1.5):
        sys.exit("raw REPL に入れませんでした")
    drain(s, 0.3)
    for i in range(0, len(script_bytes), 256):
        s.write(script_bytes[i:i + 256])
        time.sleep(0.03)
    s.write(b"\x04")
    out = drain(s, wait)
    s.write(b"\x02"); drain(s, 0.4)
    return out.decode("utf-8", "replace")


def identify(port):
    """そのポートの機種名を返す。判別できなければ None。"""
    try:
        s = serial.Serial(port, 115200, timeout=0.2)
    except Exception:
        return None
    try:
        if not enter_repl(s, tries=20):
            return None
        drain(s, 0.3)
        out = raw_exec(s, b"import os\nprint(os.uname().machine)\n", 3.0)
        for line in out.splitlines():
            line = line.strip()
            if "M5STACK" in line:
                # raw REPL は実行開始の合図として "OK" を先に返すので、
                # 1行目にそれが付いてくる。機種名だけを取り出す。
                i = line.find("M5STACK")
                return line[i:]
        return None
    finally:
        s.close()


def find_m5go(explicit=None):
    if explicit:
        return explicit
    ports = sorted(glob.glob("/dev/cu.usbserial-*"))
    if not ports:
        sys.exit("USBシリアルが見つかりません。M5Goを接続してください。")
    if len(ports) == 1:
        return ports[0]
    print("複数のポートがあるため機種を判別します（各機器がリセットされます）")
    hits = []
    for p in ports:
        m = identify(p)
        print("  %-32s %s" % (p, m or "判別できず"))
        if m and M5GO_MARKER in m:
            hits.append(p)
    if not hits:
        sys.exit("M5Go が見つかりません。--port で明示指定してください。")
    if len(hits) > 1:
        sys.exit("M5Go が複数あります。--port で指定してください:\n  " + "\n  ".join(hits))
    return hits[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="書き込まずRAMで実行")
    ap.add_argument("--list", action="store_true", help="接続機器を判別して一覧表示")
    ap.add_argument("--port", help="ポートを明示指定")
    a = ap.parse_args()

    if a.list:
        ports = sorted(glob.glob("/dev/cu.usbserial-*"))
        if not ports:
            print("USBシリアルが見つかりません")
            return
        print("接続中の機器（判別のため各機器がリセットされます）:")
        for p in ports:
            m = identify(p)
            mark = " <- M5Go" if m and M5GO_MARKER in m else ""
            print("  %-32s %s%s" % (p, m or "判別できず", mark))
        return

    if not os.path.exists(SRC_SECRETS):
        sys.exit("secrets.py がありません。secrets.py.example をコピーして\n"
                 "Wi-FiのSSIDとパスワードを記入してください。")
    secrets_code = open(SRC_SECRETS, "rb").read()
    if "ここにパスワード".encode() in secrets_code:
        sys.exit("secrets.py の WIFI_PASSWORD が未記入です。")
    main_code = open(SRC_MAIN, "rb").read()

    port = find_m5go(a.port)
    print("PORT:", port)
    s = serial.Serial(port, 115200, timeout=0.2)
    if not enter_repl(s):
        sys.exit("REPLに入れませんでした。USBを挿し直してみてください。")

    if a.run:
        pre = (b"_s=" + repr(secrets_code).encode() + b"\n"
               b"f=open('/flash/secrets.py','wb'); f.write(_s); f.close()\n"
               b"print('wrote /flash/secrets.py')\n")
        print(raw_exec(s, pre, 4.0))
        print("=== RAM実行（20秒表示）===")
        s.write(b"\x01"); drain(s, 1.5); drain(s, 0.3)
        for i in range(0, len(main_code), 256):
            s.write(main_code[i:i + 256]); time.sleep(0.03)
        s.write(b"\x04")
        t = time.time()
        while time.time() - t < 20:
            d = s.read(4096)
            if d:
                sys.stdout.write(d.decode("utf-8", "replace")); sys.stdout.flush()
        s.write(b"\x03\x03"); drain(s, 1.0)
        s.write(b"\x02"); drain(s, 0.4)
        s.close()
        return

    # boot_option = 0 は「main.py を直接実行する」。
    # 既定の 1 はスタートアップメニュー用で、この場合 boot.py は main.py を実行しない。
    # ここを設定しないと、書き込んでも起動時に何も動かないので必須。
    script = (b"_s=" + repr(secrets_code).encode() + b"\n"
              b"f=open('/flash/secrets.py','wb'); f.write(_s); f.close()\n"
              b"_c=" + repr(main_code).encode() + b"\n"
              b"f=open('/flash/main.py','wb'); f.write(_c); f.close()\n"
              b"import os, esp32\n"
              b"print('secrets.py:', os.stat('/flash/secrets.py')[6], 'bytes')\n"
              b"print('main.py   :', os.stat('/flash/main.py')[6], 'bytes')\n"
              b"nvs = esp32.NVS('uiflow')\n"
              b"nvs.set_u8('boot_option', 0)\n"
              b"nvs.commit()\n"
              b"print('boot_option =', nvs.get_u8('boot_option'), '(0 = run main.py)')\n")
    print(raw_exec(s, script, 6.0))

    print("=== 再起動して起動ログを表示 ===")
    s.write(b"import machine\r\n"); time.sleep(0.2)
    s.write(b"machine.reset()\r\n")
    print(drain(s, 30.0).decode("utf-8", "replace"))
    s.close()


if __name__ == "__main__":
    main()
