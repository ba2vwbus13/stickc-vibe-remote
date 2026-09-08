# StickC 台帳 —— PC側だけが持ちます。デバイスには入りません。
#
# ★ここを編集しても、既存機体への再書き込みは不要です。
#   デバイスは自分のMACを名乗るだけで、名前を決めるのはPC側だからです。
#
# 機体の追加手順:
#   1. 新しい機体の電源を入れてAPに繋がるのを待つ
#   2. python3 vibe.py --scan   （LANを探索してMACとIPを一覧表示）
#   3. 未登録として出てきたMACを、下の DEVICES に名前付きで追加

DEVICES = {
    # id: (MACアドレス小文字, 表示名)
    1: ("10:06:1c:27:c4:74", "stick1"),
    2: ("10:06:1c:27:c1:9c", "stick2"),
}

# 探索するネットワーク。APのIP帯に合わせてください。
SUBNET_PREFIX = "192.168.11."
SCAN_RANGE = range(2, 255)


def by_mac(mac):
    """MACから (id, 名前) を引く。未登録なら None。"""
    mac = mac.lower()
    for dev_id, (m, name) in DEVICES.items():
        if m.lower() == mac:
            return dev_id, name
    return None


def by_key(key):
    """id でも 名前 でも引いて (id, 名前, MAC) を返す。"""
    if isinstance(key, str) and key.isdigit():
        key = int(key)
    if isinstance(key, int):
        if key in DEVICES:
            return key, DEVICES[key][1], DEVICES[key][0]
        return None
    for dev_id, (m, name) in DEVICES.items():
        if name == key:
            return dev_id, name, m
    return None


def all_devices():
    """(id, 名前, MAC) を id 順に返す。"""
    return [(i, DEVICES[i][1], DEVICES[i][0]) for i in sorted(DEVICES)]
