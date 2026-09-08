# M5StickC Plus2 振動リモコン

PC から Wi-Fi 経由で M5StickC Plus2 の Vibration HAT を振動させる。
複数台を個別／同時に指定できる。インターネット不要、同一LAN内で完結する。

```
PC (vibe.py)  ──HTTP──>  StickC Plus2 (vibe_server.py)  ──GPIO26──>  Vibration HAT
```

## 設計方針：台帳はPC側だけが持つ

デバイスは **自分のMACアドレスを名乗るだけ** の存在で、名前もIDも持たない。
「どのMACがどの名前か」は PC 側の `devices.py` だけが知っている。
PC は起動時にLANを探索して「MAC ↔ IP」の対応を見つける。

この設計の利点は、**機体を追加・改名しても既存機体への再書き込みが不要**なこと。
全機体に完全に同じファイルが入る。

デバイスはDHCPでIPを受け取る。IPを固定したいときは
**AP側のDHCP予約（MACアドレス固定割当）** を使う。デバイスのコードは変えなくてよい。

## 実機で確定済みの値（2026-09-08 検証）

| 項目 | 値 |
|---|---|
| 機種 | M5StickC Plus2 (ESP32-PICO-V3-02 / 8MB / PSRAM) |
| ファーム | UIFlow2 v2.5.2 (MicroPython v1.27.0) |
| **振動ピン** | **GPIO 26** |
| 電源保持 | GPIO 4 を HIGH（バッテリー駆動時に必須） |
| AP | Buffalo-G-XXXX（2.4GHz）、GW 192.168.11.1 |
| 登録機体 | stick1 `10:06:1c:27:c4:74` / stick2 `10:06:1c:27:c1:9c` |

Vibration HAT のピンは推測せず、候補を1本ずつ動かして特定した（`find_vibe_pin.py`）。

## セットアップ

Wi-Fi認証情報は `secrets.py` に分離してあり、Gitには含まれない。

```
cp secrets.py.example secrets.py
# secrets.py を編集してSSIDとパスワードを記入
```

`deploy.py` が `secrets.py` と `vibe_server.py` の両方をデバイスへ転送する。

必要なもの: Python 3 + `pyserial`（`pip install pyserial`）、`esptool`。

## 使い方

```
python3 vibe.py --scan              # LANを探索して機体を見つける
python3 vibe.py --list              # 一覧
python3 vibe.py --id 1 800          # id=1 を800ms
python3 vibe.py --name stick2 500   # 名前で指定
python3 vibe.py --id 1,2 500        # 複数指定
python3 vibe.py --all 300           # 全機体を同時に
python3 vibe.py --ip 192.168.11.3 500   # 探索せず直接IP指定
```

`--all` と複数指定は**同時に送信**する（順番に送ると機体ごとに振動がずれるため）。
IPはキャッシュ（`.devices_cache.json`）に保存され、応答しなければ自動で再探索する。

## キーを押している間だけ震わせる（`vibe_hold.py`）

キーを**押している間ずっと**震え、離すと止まる。キーごとに機体を割り当てる。

```
python3 vibe_hold.py                  # 台帳の全機体を 1,2,3... に割り当てて起動
python3 vibe_hold.py --id 1,2         # 対象を絞る
python3 vibe_hold.py --keys jkl       # 割り当てるキーを変える
python3 vibe_hold.py --map 1=stick1,2=stick2   # 明示的に割り当てる
python3 vibe_hold.py --ip 192.168.11.7         # 探索せず直接IP指定
```

起動すると割り当て表が出る。`a` を押すと全機体が同時に震える（`--all-key` で変更、
空文字で無効）。複数キーを同時に押せば複数台が同時に震える。`q` / ESC / Ctrl-C で終了。

```
キー     名前         IP               方式
1      stick1     192.168.11.7     hold
2      stick2     192.168.11.8     hold
a      (全機体)      -                hold
```

### 振動のさせ方が2通りある（起動時に機体ごとに自動判定）

| 方式 | 条件 | 挙動 |
|---|---|---|
| `hold` | `/hold` を持つファーム | 押している間ずっとONのまま。離すと即停止 |
| `pulse` | `/vibe` しか無い旧ファーム（**書き込み不要**） | 短いパルスを連投して繋げる |

`/vibe` は指定時間ぶんデバイス側でブロックするので、途中で止められず長押しに使えない。
そこで `/hold`（ONにして期限だけ設定し即座に返す）と `/off` を追加した。PC側は
押している間 250ms ごとに `/hold?ms=900` を送り直し、離したら `/off` を送る。

**PC側が落ちてもデバイスは自力で止まる。** `/hold` の期限を過ぎると
デバイスのウォッチドッグが振動を切る（実測: 強制終了から約 830ms で停止）。
`/hold?ms=0` は「対応しているか」の問い合わせで、振動させずに答える。

旧ファームのままでも `pulse` 方式で動く。実測でパルス間の隙間は **約2ms**
なので体感は連続振動と変わらない。ただし離してから止まるまで最大 `PULSE_MS`
（既定200ms）残る。`hold` にするには `python3 deploy.py` で書き込み直す。

### キーの押し下げ／離しの取り方も2通り

| 方式 | 条件 | 挙動 |
|---|---|---|
| `pynput` | `pip install pynput` 済み | 本物の押下/開放イベント。正確 |
| `stdin` | 追加インストール不要（既定） | オートリピートの途切れから離したと推定 |

端末はキーを**離したこと**を教えてくれないので、`stdin` 方式では
「オートリピートが来なくなった＝離した」と推定する。

**この猶予は macOS のキーリピート設定より長くしないといけない。** 短いと
押し続けている最中に一度振動が切れる（リピート開始待ちを「離した」と誤判定するため）。
そこで起動時に `defaults read -g InitialKeyRepeat / KeyRepeat` を読んで自動で合わせ、
実測値を起動時に表示する。

```
※ stdin方式は端末のオートリピートから押し続けを推定します。
   macOSの設定: リピート開始まで 1133ms / 間隔 100ms
   → 短く叩くと最大 1383ms 震えます（離した判定がこの時間かかるため）。
   → 押し続けている最中は 280ms で追従します。
```

macOSの既定は **リピート開始まで 1133ms**（`InitialKeyRepeat`=68）と長い。
そのため「短く叩いただけで1.4秒震える」ことになる。キビキビさせるには:

- **システム設定 > キーボード > 「キーのリピート入力認識までの時間」を最短に**
  （`InitialKeyRepeat`=15 → 250ms。猶予は 500ms まで縮む）
- または `pip install pynput`（macOS は **システム設定 > プライバシーとセキュリティ >
  アクセシビリティ** でターミナルに許可が要る。無反応なら `--stdin` で戻せる）

**押し続けている最中**の追従はリピート間隔から決まるので、初期遅延が長くても速い
（既定で280ms）。長押しが主用途なら既定のままでも実用になる。

調整用の定数は `vibe_hold.py` 冒頭にまとめてある
（`PULSE_MS` / `HOLD_WATCHDOG_MS` / `KEEPALIVE_S`）。

## 機体を追加する

**既存機体への再書き込みは不要。**

1. 新しい機体を工場出荷状態から使うなら、まず下記「工場出荷状態から UIFlow2 へ」を実施
2. `vibe_server.py` を書き込む（USB接続して `python3 deploy.py`）
3. 電源を入れてAPに繋がるのを待つ
4. `python3 vibe.py --scan` — 未登録のMACが表示され、追記用の行がそのまま出る
5. `devices.py` の `DEVICES` にその行を貼る

```python
DEVICES = {
    1: ("10:06:1c:27:c4:74", "stick1"),
    2: ("10:06:1c:27:c1:9c", "stick2"),
}
```

---

# 工場出荷状態から UIFlow2 へ

新品の M5StickC Plus2 には Arduino製の工場デモが入っており、**MicroPython が無い**ため
`deploy.py` は使えない。まず UIFlow2 を書き込む。

工場デモが入っているかは、起動メッセージで判別できる。

```
board: 5
normal mode
mic init ok
imu test
```

## M5Burner は使えない（このMacでは）

`/Applications/M5Burner.app` (v3.0.0) はインストール済みだが機能しない。

- アプリが API を `http://m5burner-api.m5stack.com`（平文HTTP / **port 80**）で
  ハードコードしているが、**現在 port 80 は閉じており 443 のみ開いている**。
  そのためファームウェア一覧が永久に空になり、書き込み対象を選べない
- 代替ホスト（`m5burner-api-fc-hk-cdn`）も port 80 は閉じている
- 加えて x86_64 のみ・コード署名が一切無く Gatekeeper にも弾かれる

**代わりに esptool を直接使う。** 以下は検証済みの手順。

## 手順

### 1. ポートとチップを確認

```
ls /dev/cu.usbserial-*
esptool.py --port /dev/cu.usbserial-XXXX --no-stub flash_id
```

`ESP32-PICO-V3-02` / `Detected flash size: 8MB` なら StickC Plus2。

### 2. ファームウェアのカタログを取得

```
curl -s -o catalog.json https://m5burner-api.m5stack.com/api/firmware
```

認証不要の公開API。約2500件のJSON配列が返る。

### 3. 該当ファームウェアを探す

```python
import json
d = json.load(open('catalog.json'))
e = [x for x in d if x.get('name') == 'UIFlow2.0 StickC Plus2'][0]
for v in sorted(e['versions'], key=lambda v: v['published_at'], reverse=True)[:5]:
    print(v['version'], v['published_at'], v['file'])
```

機種ごとのエントリ名（`name` / `category`）:

| 機種 | name | category |
|---|---|---|
| StickC Plus2 | `UIFlow2.0 StickC Plus2` | `stickc` |
| Core / M5GO / Gray | `UIFlow2.0` | `core` |
| Core2 / Tough | `UIFlow2.0` | `core2 & tough` |
| CoreS3 | `UIFlow2.0` | `cores3` |

**M5Go(Core)は 4MB版と16MB版があるので、フラッシュ容量に合うほうを選ぶこと。**

### 4. bin を取得して検証

```
curl -s -o fw.bin https://m5burner-cdn.m5stack.com/firmware/<file>
```

```python
d = open('fw.bin','rb').read()
print(len(d))
print('bootloader:', hex(d[0x1000]))   # ESP32(無印)は 0x1000 に 0xe9
```

**ESP32(無印)はブートローダが 0x1000 配置**なので、0x0起点フルイメージの
先頭4KBが `ff` 埋めなのは正常（S3系は0x0起点なのでここが違う）。

### 5. 消去して書き込む

```
esptool.py --port /dev/cu.usbserial-XXXX --chip esp32 --baud 115200 erase-flash
esptool.py --port /dev/cu.usbserial-XXXX --chip esp32 --baud 115200 \
    write-flash --flash-size keep 0x0 fw.bin
```

`Hash of data verified.` が出れば成功。所要時間は StickC Plus2 (8MB) で約6分、
M5Go (16MB) で約5分半。

**ボーレートは 115200 にすること。** このUSBシリアル変換は 460800 / 921600 では
read-flash が途中で切れる（`Serial data stream stopped`）。

### 6. 確認

```
python3 deploy.py --whoami
```

MAC が表示されれば MicroPython が動いている。

---

## 動作確認済み（2026-09-08）

```
$ python3 vibe.py --scan
探索中: 192.168.11.2-254 ...
完了 (0.9秒) — port80応答 2件 / StickC 1台

$ python3 vibe.py --name stick1 600 -> OK 600 ms
$ python3 vibe.py --all 500         -> stick1 / stick2 が同時に
$ python3 vibe.py 9999              -> OK 3000 ms   (MAX_MSで丸められる)
```

2台での同時振動の**送信タイミングのずれは 0.23 / 0.63 / 1.66 ms**（3回計測）。
体感で分かるのは数十ms以上なので実用上は同時とみなせる。

`vibe_hold.py` は偽デバイス（`vibe_server.py` と同じ応答をする擬似サーバ）を
相手にGPIOの波形を記録して検証した。

- `hold` 方式: 押している間ずっと1本のON（切れ目ゼロ）
- `pulse` 方式: パルス間の隙間 平均1.9ms / 最大2.6ms
- 全機体キーで2台が同時にON（ずれ 1ms未満）
- 押している最中にPC側を `SIGKILL` → 約830msでデバイスが自力停止
- このMacの実設定（リピート開始1133ms）で3秒押し続け → 途切れず1本の3295ms
  （猶予を650ms固定にすると 820ms + 2253ms に分断されることを確認済み）

## ハマった点（重要）

### 1. boot_option を 0 にしないと main.py が動かない

UIFlow2 の `boot.py` は `boot_option` が既定値の 1（スタートアップメニュー）のとき
**main.py を実行しない**。書き込みが成功していても起動時に何も起きない。
`deploy.py` が `boot_option = 0` を設定するので通常は意識不要。

### 2. 学内プロキシで PC からのリクエストが届かない

macOS にシステムプロキシ `proxy.example.ac.jp:8080` が設定されており、
**urllib はこれを自動的に使う**。StickC はLAN内の機器なのでプロキシ経由では届かず
タイムアウトする。`vibe.py` は空の `ProxyHandler` で明示的に迂回している。

curl は macOS のシステムプロキシを読まないため、**curl では成功するのに
Pythonスクリプトだけ失敗する**という紛らわしい症状になる。

```
scutil --proxy
python3 -c "import urllib.request as u; print(u.getproxies())"
```

### 3. シリアルポートを開くとデバイスがリセットされる

pyserial でポートを開閉すると DTR/RTS がトグルして ESP32 がリセットする。
動作中のサーバを観測しようとしてシリアルを開くと、その瞬間に再起動が始まり
「サーバが応答しない」ように見える。**ネットワーク経由の動作確認中はシリアルを開かないこと。**

### 4. 電源については問題なし

Wi-Fi接続中に1500ms振動させてもブラウンアウト・リセットは発生しなかった。

## つながらないときの切り分け

1. **APは2.4GHzか** — ESP32は5GHz非対応。Buffalo機はSSIDの `-G-` が2.4GHz、`-A-` が5GHz
2. **`python3 vibe.py --scan`** — 機体が見つかるか。見つからなければデバイス側の問題
3. **クライアント間通信が許可されているか** — プライバシーセパレータ / AP isolation をオフ
4. **WPA3専用になっていないか** — WPA2-PSK にする
5. デバイスの画面に出るIPと、`--scan` の結果が一致しているか
6. バンドステアリング（2.4/5GHzで同じSSID）は避ける

## ファイル

| ファイル | 役割 |
|---|---|
| `devices.py` | **台帳（PC側のみ）。MAC→名前。ここを編集しても再書き込み不要** |
| `vibe_server.py` | StickC本体側。全機体共通。設定はWi-Fi情報のみ |
| `vibe.py` | PC側。探索・キャッシュ・振動指示 |
| `vibe_hold.py` | PC側。**キーを押している間だけ振動**。キーごとに機体を選ぶ |
| `deploy.py` | `vibe_server.py` を StickC に書き込む |
| `find_vibe_pin.py` | 振動ピン特定用（記録。通常は不要） |
| `.devices_cache.json` | 探索結果のキャッシュ（自動生成、Git除外） |
| `secrets.py` | **Wi-Fi認証情報。Git除外。`secrets.py.example` からコピーして作る** |

## 補足

- 振動時間は安全のため **最大3秒** に制限している（`MAX_MS`）
- 周囲のAPスキャンでは ch1/4/6/9/11 が使用中。ch9 に非常に強いAP(-19dBm)があるため、
  反応が不安定なら AP のチャンネルを ch1 か ch6 に手動設定する
- Wi-Fiパスワードは `secrets.py` に分離済み（`.gitignore` で除外）。
  ただし**デバイスのフラッシュ上には平文で保存される**ため、機体を貸し出す際は注意
