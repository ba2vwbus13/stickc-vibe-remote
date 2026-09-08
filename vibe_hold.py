#!/usr/bin/env python3
"""キーを押している間だけ StickC を振動させる。キーごとに機体を選ぶ。

    python3 vibe_hold.py                  # 台帳の全機体を 1,2,3... に割り当てて起動
    python3 vibe_hold.py --id 1,2         # 対象を絞る
    python3 vibe_hold.py --keys jkl       # 割り当てるキーを変える
    python3 vibe_hold.py --map 1=stick1,2=stick2   # 明示的に割り当てる
    python3 vibe_hold.py --ip 192.168.11.7         # 探索せず直接IP指定

起動すると「どのキーがどの機体か」の表が出る。キーを押している間その機体が震え、
離すと止まる。複数キーを同時に押せば複数台が同時に震える。q / ESC / Ctrl-C で終了。

台帳(devices.py)・探索・キャッシュは vibe.py のものをそのまま使う。

------------------------------------------------------------------
振動の出し方は機体のファームによって2通り。起動時に自動で判定する。

  hold  : /hold と /off を持つ新しいファーム。押している間ずっとONのまま。
          PCが落ちても機体側のウォッチドッグが必ず止める。
          → vibe_server.py を deploy.py で書き込むとこちらになる。

  pulse : /vibe しか無い現行ファーム（書き込み不要）。短いパルスを連続で
          投げ続けて「震え続けている」ように見せる。パルスの切れ目に数msの
          隙間があり、離してから止まるまで最大 PULSE_MS だけ遅れる。

------------------------------------------------------------------
キーの押し下げ／離しの取り方も2通り。

  pynput : 本物のキー押下/開放イベントが取れる。こちらが正確。
           pip install pynput が必要で、macOSでは「システム設定 >
           プライバシーとセキュリティ > アクセシビリティ」で
           ターミナルに許可を与える必要がある。

  stdin  : 標準入力をrawモードで読む。追加インストール不要だが、端末は
           キーを離したことを教えてくれないので「オートリピートが途切れた
           =離した」と推定する。押し始めの数百ms（OSのリピート開始待ち）と
           離してからの十数msに遅れが出る。
"""
import argparse
import os
import select
import subprocess
import sys
import threading
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import devices
import vibe

# ------------------------------------------------------------
# 調整用の定数
# ------------------------------------------------------------
PULSE_MS = 200          # pulseモードの1パルス長。短いほど離した時の追従が良いが
                        # パルス間の隙間の回数が増える
HOLD_WATCHDOG_MS = 900  # holdモードでPCが落ちた時に機体が自力で止まるまで
KEEPALIVE_S = 0.25      # holdモードの延命信号の間隔（ウォッチドッグより十分短く）
HTTP_TIMEOUT = 3        # 押している最中に長く待たされると追従が壊れるので短め

DEFAULT_KEYS = "1234567890"
ALL_KEY = "a"           # 全機体を同時に震わせるキー
QUIT_KEYS = ("q", "\x03", "\x1b")

# stdinモードの「離した」判定に使う猶予。macOSのキーリピート設定から決める。
# 「リピート開始まで」より短くすると、押し続けている最中に一度振動が切れてしまう。
STDIN_FIRST_TIMEOUT = 1.4    # 起動時に実際の設定を読んで上書きする
STDIN_MIN_TIMEOUT = 0.09
STDIN_MARGIN = 0.25          # 取りこぼしを避けるための上乗せ


def load_key_repeat():
    """macOSのキーリピート設定(1/60秒単位)を読み、判定の待ち時間を合わせる。

    既定は InitialKeyRepeat=68 (1133ms) / KeyRepeat=6 (100ms)。
    初期遅延が長いほど、離してから振動が止まるまでの遅れも長くなる。
    システム設定 > キーボード > 「キーのリピート入力認識までの時間」を
    短くするとキビキビ動く。"""
    global STDIN_FIRST_TIMEOUT, STDIN_MIN_TIMEOUT

    def read(key, default):
        try:
            r = subprocess.run(["defaults", "read", "-g", key],
                               capture_output=True, text=True, timeout=2)
            return float(r.stdout.strip()) if r.returncode == 0 else default
        except Exception:
            return default

    initial = read("InitialKeyRepeat", 68) / 60.0
    rate = read("KeyRepeat", 6) / 60.0
    STDIN_FIRST_TIMEOUT = initial + STDIN_MARGIN
    STDIN_MIN_TIMEOUT = max(0.06, rate * 2.5 + 0.03)
    return initial, rate

_print_lock = threading.Lock()
_raw_mode = False
KEY_REPEAT = (68 / 60.0, 6 / 60.0)   # 起動時に実測値で上書きする


def out(msg=""):
    """rawモード中は改行が \\n だけだと行頭に戻らないので \\r\\n で出す。"""
    with _print_lock:
        sys.stdout.write(msg + ("\r\n" if _raw_mode else "\n"))
        sys.stdout.flush()


# ------------------------------------------------------------
# 1機体ぶんの振動を受け持つワーカー
# ------------------------------------------------------------
class Stick(object):
    """押されている間ずっと振動させ続ける。1機体につき1スレッド。

    キー入力スレッドは press()/release() を呼ぶだけで、HTTPは全部こちらの
    スレッドが投げる。ネットワークが詰まってもキー入力が止まらないようにするため。
    """

    def __init__(self, name, ip, mode):
        self.name = name
        self.ip = ip
        self.mode = mode          # "hold" または "pulse"
        self.errors = 0
        self._down = False
        self._quit = False
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def press(self):
        with self._cv:
            if self._down:
                return False
            self._down = True
            self._cv.notify_all()
        return True

    def release(self):
        with self._cv:
            if not self._down:
                return False
            self._down = False
            self._cv.notify_all()
        return True

    def shutdown(self):
        with self._cv:
            self._down = False
            self._quit = True
            self._cv.notify_all()
        self._thread.join(timeout=2)
        if self.mode == "hold":
            self._get("/off")     # 取りこぼしが無いよう終了時にもう一度止める

    # -- HTTP ------------------------------------------------
    def _get(self, path):
        try:
            return vibe._get("http://%s%s" % (self.ip, path), HTTP_TIMEOUT)
        except urllib.error.URLError as e:
            self._note_error("接続できません (%s)" % e.reason)
        except Exception as e:
            self._note_error("%s: %s" % (type(e).__name__, e))
        return None

    def _note_error(self, msg):
        self.errors += 1
        # 押しっぱなしで失敗し続けると画面が埋まるので最初の1回だけ出す
        if self.errors == 1:
            out("NG  %-10s %s" % (self.name, msg))

    # -- 本体 ------------------------------------------------
    def _run(self):
        while True:
            with self._cv:
                while not self._down and not self._quit:
                    self._cv.wait()
                if self._quit:
                    return
            if self.mode == "hold":
                self._hold_once()
            else:
                self._pulse_once()

    def _hold_once(self):
        """ONにして、延命間隔だけ待つ。その間に離されたら即OFF。"""
        self._get("/hold?ms=%d" % HOLD_WATCHDOG_MS)
        with self._cv:
            self._cv.wait_for(lambda: not self._down or self._quit, KEEPALIVE_S)
            still_down = self._down and not self._quit
        if not still_down:
            self._get("/off")

    def _pulse_once(self):
        """機体は /vibe の間ブロックするので、応答が返る=振動が終わった時。
        すぐ次を投げると数msの隙間だけで繋がる。"""
        self._get("/vibe?ms=%d" % PULSE_MS)


# ------------------------------------------------------------
# 機体の準備
# ------------------------------------------------------------
def probe_mode(ip):
    """/hold を持つファームか調べる。

    ms=0 は能力確認用で、新ファームは振動させずに "HOLD 0 ms" と答える。
    /hold を知らない旧ファームは未知パスとしてヘルプ文を返してくるので、
    どちらも機体を震わせずに判定できる。"""
    try:
        body = vibe._get("http://%s/hold?ms=0" % ip, HTTP_TIMEOUT)
    except Exception:
        return "pulse"
    return "hold" if body.upper().startswith("HOLD") else "pulse"


def resolve_entries(args):
    """--id / --name / --all / --ip から [(表示名, IP)] を作る。"""
    if args.ip:
        return [(args.ip, args.ip)]

    keys = []
    for src in (args.id, args.name):
        if src:
            keys += [k.strip() for k in src.split(",") if k.strip()]

    if keys:
        entries = []
        for k in keys:
            found = devices.by_key(k)
            if not found:
                sys.exit("台帳に '%s' がありません。devices.py を確認してください。" % k)
            entries.append(found)
    else:
        entries = devices.all_devices()
        if not entries:
            sys.exit("devices.py に機体が登録されていません。")

    cache = vibe.load_cache()
    targets = []
    for dev_id, name, mac in entries:
        ip, cache = vibe.resolve_ip(mac, cache)
        if not ip:
            out("NG  %-10s 見つかりません（電源とAP接続を確認）" % name)
            continue
        targets.append((name, ip))
    return targets


def build_keymap(args, targets):
    """キー -> [Stick] の対応を作る。ALL_KEY は全機体に繋ぐ。"""
    sticks = {}
    for name, ip in targets:
        mode = probe_mode(ip)
        sticks[name] = Stick(name, ip, mode)

    keymap = {}
    if args.map:
        for pair in args.map.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                sys.exit("--map は キー=機体 の形で書いてください (例: 1=stick1)")
            key, ref = (s.strip() for s in pair.split("=", 1))
            if len(key) != 1:
                sys.exit("--map のキーは1文字にしてください: '%s'" % key)
            found = devices.by_key(ref)
            name = found[1] if found else ref
            if name not in sticks:
                sys.exit("'%s' は対象に含まれていません（--id で絞っていませんか）" % ref)
            if key in keymap:
                sys.exit("キー '%s' が二重に割り当てられています（%s と %s）。"
                         % (key, keymap[key][0].name, name))
            keymap[key] = [sticks[name]]
    else:
        keys = args.keys or DEFAULT_KEYS
        if len(keys) < len(targets):
            sys.exit("キーが足りません（機体 %d台 に対しキー %d個）。--keys で増やしてください。"
                     % (len(targets), len(keys)))
        if len(set(keys[:len(targets)])) < len(targets):
            sys.exit("--keys に同じキーが重複しています: '%s'" % keys)
        for key, (name, _ip) in zip(keys, targets):
            keymap[key] = [sticks[name]]

    all_key = args.all_key
    if all_key:
        if all_key in keymap:
            sys.exit("全機体キー '%s' が個別のキーと重なっています。--all-key で変えてください。"
                     % all_key)
        keymap[all_key] = list(sticks.values())

    return keymap, list(sticks.values())


def show_table(keymap, sticks, backend):
    out("")
    out("%-6s %-10s %-16s %s" % ("キー", "名前", "IP", "方式"))
    for key in sorted(keymap, key=lambda k: (len(keymap[k]) > 1, k)):
        group = keymap[key]
        if len(group) == 1:
            s = group[0]
            out("%-6s %-10s %-16s %s" % (key, s.name, s.ip, s.mode))
        else:
            out("%-6s %-10s %-16s %s"
                % (key, "(全機体)", "-", ",".join(sorted({g.mode for g in group}))))
    out("")
    out("入力: %s   終了: q / ESC / Ctrl-C" % backend)
    if any(s.mode == "pulse" for s in sticks):
        out("※ pulse方式の機体は、離してから最大 %dms 振動が残ります。" % PULSE_MS)
        out("   vibe_server.py を書き込み直すと hold方式（即停止）になります。")
    if backend == "stdin":
        initial, rate = KEY_REPEAT
        out("※ stdin方式は端末のオートリピートから押し続けを推定します。")
        out("   macOSの設定: リピート開始まで %.0fms / 間隔 %.0fms"
            % (initial * 1000, rate * 1000))
        out("   → 短く叩くと最大 %.0fms 震えます（離した判定がこの時間かかるため）。"
            % (STDIN_FIRST_TIMEOUT * 1000))
        out("   → 押し続けている最中は %.0fms で追従します。"
            % (STDIN_MIN_TIMEOUT * 1000))
        if initial > 0.5:
            out("   キビキビさせるには システム設定 > キーボード >")
            out("   「キーのリピート入力認識までの時間」を短くするか、pip install pynput。")
    out("")


# ------------------------------------------------------------
# キー入力（2方式）
# ------------------------------------------------------------
def run_pynput(keymap, on_press, on_release):
    from pynput import keyboard

    stop = threading.Event()

    def key_char(key):
        try:
            if key.char:
                return key.char.lower()
        except AttributeError:
            pass
        if key == keyboard.Key.esc:
            return "\x1b"
        return None

    def pressed(key):
        c = key_char(key)
        if c is None:
            return
        if c in QUIT_KEYS and c not in keymap:
            stop.set()
            return False
        # pynput も押しっぱなしで on_press を繰り返すが press() が冪等なので害はない
        on_press(c)

    def released(key):
        c = key_char(key)
        if c is not None:
            on_release(c)

    listener = keyboard.Listener(on_press=pressed, on_release=released)
    listener.start()
    try:
        while not stop.is_set() and listener.running:
            stop.wait(0.2)
    finally:
        listener.stop()


def run_stdin(keymap, on_press, on_release):
    """端末はキーを離したことを教えてくれない。オートリピートが途切れたら
    離したとみなす。最初はOSのリピート開始遅延ぶん長めに待ち、リピート間隔が
    分かった時点で待ち時間を詰める。"""
    global _raw_mode
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    last = {}      # キー -> 最後に届いた時刻
    timeout = {}   # キー -> 離した判定までの猶予
    try:
        tty.setraw(fd)
        _raw_mode = True
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.02)
            now = time.monotonic()

            if ready:
                chunk = os.read(fd, 64).decode("utf-8", "replace")
                for i, ch in enumerate(chunk):
                    c = ch.lower()
                    # 矢印キー等は ESC で始まる。単独のESCだけ終了として扱う
                    if c == "\x1b" and len(chunk) > 1:
                        break
                    if c in QUIT_KEYS and c not in keymap:
                        return
                    if c not in keymap:
                        continue
                    if c in last:
                        gap = now - last[c]
                        if gap < 0.4:   # オートリピートとみなせる間隔なら学習する
                            timeout[c] = max(STDIN_MIN_TIMEOUT, gap * 2.5 + 0.03)
                    else:
                        timeout[c] = STDIN_FIRST_TIMEOUT
                        on_press(c)
                    last[c] = now

            for c in list(last):
                if now - last[c] > timeout[c]:
                    del last[c]
                    on_release(c)
    finally:
        _raw_mode = False
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


# ------------------------------------------------------------
def main():
    global PULSE_MS
    p = argparse.ArgumentParser(
        description="キーを押している間だけ StickC を振動させる",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--id", help="対象の機体ID。カンマ区切り (例: 1,2)")
    p.add_argument("--name", help="対象の機体名。カンマ区切り")
    p.add_argument("--ip", help="探索せずIP直接指定")
    p.add_argument("--keys", help="割り当てるキーを並べる (既定: %s)" % DEFAULT_KEYS)
    p.add_argument("--map", help="明示的な割り当て (例: 1=stick1,2=stick2)")
    p.add_argument("--all-key", default=ALL_KEY,
                   help="全機体を同時に震わせるキー (既定: %s。空文字で無効)" % ALL_KEY)
    p.add_argument("--scan", action="store_true", help="起動前にLANを再探索する")
    p.add_argument("--stdin", action="store_true",
                   help="pynput が入っていても標準入力方式を使う")
    p.add_argument("--pulse-ms", type=int, default=PULSE_MS,
                   help="pulse方式の1パルス長(ミリ秒、既定 %d)" % PULSE_MS)
    a = p.parse_args()

    PULSE_MS = a.pulse_ms

    if a.scan:
        vibe.scan()

    targets = resolve_entries(a)
    if not targets:
        sys.exit("対象の機体が1台も見つかりませんでした。python3 vibe.py --scan を試してください。")

    keymap, sticks = build_keymap(a, targets)

    global KEY_REPEAT
    KEY_REPEAT = load_key_repeat()

    backend = "stdin"
    if not a.stdin:
        try:
            import pynput  # noqa: F401
            backend = "pynput"
        except Exception:
            backend = "stdin"

    show_table(keymap, sticks, backend)

    for s in sticks:
        s.start()

    def on_press(key):
        group = keymap.get(key)
        if not group:
            return
        # any(...) のジェネレータだと最初のTrueで打ち切られ、2台目以降が
        # 押されないままになる。必ず全機体に伝えてから判定する。
        changed = [s.press() for s in group]
        if any(changed):
            out("▓ %s" % ", ".join(s.name for s in group))

    def on_release(key):
        group = keymap.get(key)
        if not group:
            return
        changed = [s.release() for s in group]
        if any(changed):
            out("░ %s" % ", ".join(s.name for s in group))

    try:
        if backend == "pynput":
            run_pynput(keymap, on_press, on_release)
        else:
            run_stdin(keymap, on_press, on_release)
    except KeyboardInterrupt:
        pass
    finally:
        for s in sticks:
            s.shutdown()
        out("終了しました。")


if __name__ == "__main__":
    main()
