#!/usr/bin/env python3
"""PCから StickC を振動させる。台帳(devices.py)はPC側だけが持つ。

    python3 vibe.py --scan                # LANを探索して機体を見つける
    python3 vibe.py --list                # 一覧（キャッシュ利用、必要なら自動探索）
    python3 vibe.py --id 1 800            # id=1 を800ms
    python3 vibe.py --name stick2 500     # 名前で指定
    python3 vibe.py --id 1,2 500          # 複数指定
    python3 vibe.py --all 300             # 全機体を同時に
    python3 vibe.py --ip 192.168.11.7 500 # 探索せず直接IP指定

デバイスはDHCPなのでIPが変わることがある。見つからないときは自動で再探索する。
IPを固定したいときは、AP側のDHCP予約(MACアドレス固定割当)を使うとよい。
"""
import argparse
import concurrent.futures
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devices

CACHE = os.path.join(HERE, ".devices_cache.json")

# 学内ネットワークではmacOSにシステムプロキシ(proxy.example.ac.jp:8080)が
# 設定されており、urllibはそれを自動的に使ってしまう。StickCはLAN内の機器なので
# プロキシを経由させてはいけない。空のProxyHandlerで明示的に迂回する。
# （curlはmacOSのシステムプロキシを読まないため、curlでは問題が起きない）
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url, timeout):
    with _opener.open(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace").strip()


# ------------------------------------------------------------
# 探索
# ------------------------------------------------------------
def _port_open(ip, port=80, timeout=0.35):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    finally:
        s.close()


def _whoami(ip):
    """port 80 が開いていて /whoami がMACを返せば StickC とみなす。"""
    try:
        mac = _get("http://%s/whoami" % ip, 2).strip().lower()
        return mac if mac.count(":") == 5 else None
    except Exception:
        return None


def scan(verbose=True):
    """LANを探索して {MAC: IP} を返し、キャッシュに保存する。"""
    ips = ["%s%d" % (devices.SUBNET_PREFIX, i) for i in devices.SCAN_RANGE]
    if verbose:
        print("探索中: %s%d-%d ..." % (devices.SUBNET_PREFIX,
                                       devices.SCAN_RANGE[0], devices.SCAN_RANGE[-1]))
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as ex:
        alive = [ip for ip, ok in zip(ips, ex.map(_port_open, ips)) if ok]
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
        macs = list(ex.map(_whoami, alive))

    found = {m: ip for ip, m in zip(alive, macs) if m}
    save_cache(found)
    if verbose:
        print("完了 (%.1f秒) — port80応答 %d件 / StickC %d台"
              % (time.time() - t0, len(alive), len(found)))
    return found


def load_cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(mapping):
    try:
        with open(CACHE, "w") as f:
            json.dump(mapping, f, indent=2)
    except Exception as e:
        print("キャッシュ保存に失敗:", e)


def resolve_ip(mac, cache, allow_rescan=True):
    """MACからIPを引く。キャッシュが古ければ再探索する。"""
    mac = mac.lower()
    ip = cache.get(mac)
    if ip and _whoami(ip) == mac:
        return ip, cache
    if not allow_rescan:
        return None, cache
    cache = scan(verbose=True)
    return cache.get(mac), cache


# ------------------------------------------------------------
# 操作
# ------------------------------------------------------------
def vibrate(ip, ms, timeout=8):
    try:
        return True, _get("http://%s/vibe?ms=%d" % (ip, ms), timeout)
    except urllib.error.URLError as e:
        return False, "接続できません (%s)" % e.reason
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def cmd_scan():
    found = scan()
    print()
    print("%-4s %-10s %-18s %s" % ("id", "名前", "MAC", "IP"))
    seen = set()
    for dev_id, name, mac in devices.all_devices():
        ip = found.get(mac.lower())
        seen.add(mac.lower())
        print("%-4d %-10s %-18s %s" % (dev_id, name, mac, ip or "見つかりません"))
    extra = [(m, ip) for m, ip in found.items() if m not in seen]
    if extra:
        print("\n--- 台帳に未登録の機体 ---")
        for m, ip in extra:
            print("     %-18s %s" % (m, ip))
        print("\ndevices.py の DEVICES に追加してください（再書き込みは不要です）:")
        nxt = max(devices.DEVICES) + 1 if devices.DEVICES else 1
        for i, (m, ip) in enumerate(extra):
            print('    %d: ("%s", "stick%d"),' % (nxt + i, m, nxt + i))


def cmd_list():
    cache = load_cache()
    if not cache:
        cache = scan()
    print("%-4s %-10s %-18s %-16s %s" % ("id", "名前", "MAC", "IP", "状態"))
    for dev_id, name, mac in devices.all_devices():
        ip = cache.get(mac.lower())
        state = "キャッシュ無し"
        if ip:
            state = "OK" if _whoami(ip) == mac.lower() else "応答なし(要 --scan)"
        print("%-4d %-10s %-18s %-16s %s" % (dev_id, name, mac, ip or "-", state))


def resolve_targets(args):
    """--id / --name / --all / --ip から [(名前, IP)] を作る。"""
    if args.ip:
        return [(args.ip, args.ip)]

    if args.all:
        entries = devices.all_devices()
    else:
        keys = []
        for src in (args.id, args.name):
            if src:
                keys += [k.strip() for k in src.split(",") if k.strip()]
        if not keys:
            return []
        entries = []
        for k in keys:
            found = devices.by_key(k)
            if not found:
                sys.exit("台帳に '%s' がありません。devices.py を確認してください。" % k)
            entries.append(found)

    cache = load_cache()
    targets = []
    for dev_id, name, mac in entries:
        ip, cache = resolve_ip(mac, cache)
        if not ip:
            print("NG  %-10s 見つかりません（電源とAP接続を確認）" % name)
            continue
        targets.append((name, ip))
    return targets


def main():
    p = argparse.ArgumentParser(description="StickC を遠隔で振動させる")
    p.add_argument("ms", nargs="?", type=int, default=300, help="振動時間(ミリ秒)")
    p.add_argument("--id", help="機体ID。カンマ区切りで複数可 (例: 1,2)")
    p.add_argument("--name", help="機体名。カンマ区切りで複数可")
    p.add_argument("--all", action="store_true", help="登録された全機体")
    p.add_argument("--ip", help="探索せずIP直接指定")
    p.add_argument("--scan", action="store_true", help="LANを探索して機体を見つける")
    p.add_argument("--list", action="store_true", help="一覧を表示")
    p.add_argument("--times", type=int, default=1, help="繰り返し回数")
    p.add_argument("--interval", type=float, default=0.4, help="繰り返し間隔(秒)")
    a = p.parse_args()

    if a.scan:
        cmd_scan(); return
    if a.list:
        cmd_list(); return

    targets = resolve_targets(a)
    if not targets:
        p.error("対象を指定してください（--id / --name / --all / --ip）")

    failed = False
    for n in range(a.times):
        # 複数台は同時に投げる（順番に投げると機体ごとに振動がずれるため）
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
            results = list(ex.map(lambda t: vibrate(t[1], a.ms), targets))
        for (name, ip), (ok, msg) in zip(targets, results):
            print("[%d/%d] %s %-10s %s" % (n + 1, a.times, "OK " if ok else "NG ", name, msg))
            if not ok:
                failed = True
        if n < a.times - 1:
            time.sleep(a.interval)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
