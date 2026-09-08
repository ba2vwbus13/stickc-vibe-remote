#!/usr/bin/env python3
"""StickC に vibe_server.py を書き込む。

    python3 deploy.py --whoami   # MACアドレスだけ表示（台帳への追加用）
    python3 deploy.py            # 書き込んで再起動、起動ログを表示
    python3 deploy.py --run      # 書き込まずRAM実行だけ試す

全機体に完全に同じファイルを入れます。台帳(devices.py)はPC側だけが持つので
デバイスには転送しません。機体を追加・改名しても既存機体の再書き込みは不要です。
複数台を用意するときは、1台ずつUSBで繋いでこれを実行してください。
"""
import argparse
import glob
import os
import sys
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_MAIN = os.path.join(HERE, "vibe_server.py")
SRC_SECRETS = os.path.join(HERE, "secrets.py")


def open_device():
    ports = sorted(glob.glob("/dev/cu.usbserial-*"))
    if not ports:
        sys.exit("USBシリアルが見つかりません。StickCを接続してください。")
    if len(ports) > 1:
        sys.exit("複数のStickCが接続されています。1台だけにしてください:\n  " +
                 "\n  ".join(ports))
    return serial.Serial(ports[0], 115200, timeout=0.2), ports[0]


def drain(s, sec):
    t = time.time(); b = b""
    while time.time() - t < sec:
        b += s.read(4096)
    return b


def enter_repl(s):
    for _ in range(30):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="書き込まずRAMで実行")
    ap.add_argument("--whoami", action="store_true", help="MACアドレスだけ表示")
    a = ap.parse_args()

    s, port = open_device()
    print("PORT:", port)
    if not enter_repl(s):
        sys.exit("REPLに入れませんでした。USBを挿し直してみてください。")

    if a.whoami:
        script = (b"import network, binascii\n"
                  b"w = network.WLAN(network.STA_IF); w.active(True)\n"
                  b"raw = binascii.hexlify(w.config('mac')).decode()\n"
                  b"mac = ':'.join(raw[i:i+2] for i in range(0,12,2))\n"
                  b"print('MAC:', mac)\n"
                  b"print('-> add this MAC to DEVICES in devices.py')\n")
        print(raw_exec(s, script, 5.0))
        s.close()
        return

    main_code = open(SRC_MAIN, "rb").read()
    if not os.path.exists(SRC_SECRETS):
        sys.exit("secrets.py がありません。secrets.py.example をコピーして\n"
                 "Wi-FiのSSIDとパスワードを記入してください。")
    secrets_code = open(SRC_SECRETS, "rb").read()
    if "ここにパスワード".encode() in secrets_code:
        sys.exit("secrets.py の WIFI_PASSWORD が未記入です。")
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
              b"print('main.py:', os.stat('/flash/main.py')[6], 'bytes')\n"
              b"try:\n"
              b"    os.remove('/flash/devices.py')\n"
              b"    print('removed old /flash/devices.py')\n"
              b"except OSError:\n"
              b"    pass\n"
              b"nvs = esp32.NVS('uiflow')\n"
              b"nvs.set_u8('boot_option', 0)\n"
              b"nvs.commit()\n"
              b"print('boot_option =', nvs.get_u8('boot_option'), '(0 = run main.py)')\n")
    print(raw_exec(s, script, 6.0))

    print("=== 再起動して起動ログを表示 ===")
    s.write(b"import machine\r\n"); time.sleep(0.2)
    s.write(b"machine.reset()\r\n")
    print(drain(s, 25.0).decode("utf-8", "replace"))
    s.close()


if __name__ == "__main__":
    main()
