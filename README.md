# ゆいしるべ — 障害物の触覚ガイド

前方の障害物を距離センサで検知し、ポケットに入れた M5StickC を振動させて知らせる。
インターネット不要。ローカルの2.4GHz Wi-Fi だけで完結する。

```
M5Go + ToF ──距離判定──> UDP探索でStickCを発見 ──HTTP──> StickC が振動
                                                    （ポケット内・バッテリー駆動）
```

PC から手動で振動させることもできる（`vibe.py` / `vibe_hold.py`）。

**2026-09-09 にエンドツーエンドで動作確認済み。**

---

## 1. クイックスタート

### 1-1. 電源を入れる

1. AP（`Buffalo-G-XXXX`、**2.4GHz**）の電源を入れる
2. StickC の電源を入れる（左側面ボタンを2秒長押し）
3. M5Go の電源を入れる

**電源投入から使えるようになるまで十数秒かかる。** 押した直後は画面も暗く、
反応が無いように見えるが正常。**15秒ほど待つこと。**

### 1-2. 動作確認

```
python3 vibe.py --scan     # StickCが見つかるか
python3 vibe.py --id 1 600 # 振動するか
```

M5Go の画面に距離が出ていれば ToF 側も動いている。
障害物を80cm以内に置くと StickC が2秒ごとに震える。

### 1-3. PC を必ず 2.4GHz に繋ぐ

**PCが5GHz側にいると、同じ `192.168.11.x` でも機器と通信できない。**
Buffalo機はSSIDが `-G-`(2.4GHz) と `-A-`(5GHz) に分かれる。

```
system_profiler SPAirPortDataType | grep Channel
```

`Channel: 9 (2GHz...)` のように 2GHz と出ていれば正しい。

---

## 2. 構成機器

| 機器 | 役割 | 書き込むファイル |
|---|---|---|
| M5Go + ToFユニット | 距離を測り、閾値を超えたら通知 | `tof_server.py` |
| M5StickC Plus2 ×2 + Vibration HAT | 振動する | `vibe_server.py` |
| PC | 開発・手動操作 | `vibe.py` / `vibe_hold.py` / `deploy.py` |

### 実機で確定済みの値

| 項目 | 値 |
|---|---|
| StickC 振動ピン | **GPIO 26** |
| StickC 電源保持 | **GPIO 4 を HIGH**（バッテリー駆動に必須） |
| ToF 接続 | Port A（SDA=G21 / SCL=G22）、I2Cアドレス `0x29` |
| ToF 初期化 | `ToFUnit(i2c=i2c0)` ※`port=` は不可 |
| ファーム | UIFlow2 v2.5.2 / MicroPython v1.27.0 |
| AP | Buffalo-G-XXXX（2.4GHz）、GW 192.168.11.1 |
| 登録機体 | stick1 `10:06:1c:27:c4:74` / stick2 `10:06:1c:27:c1:9c` |

いずれも推測せず実機で確定させた。ENVユニットが `port=` ではなく `i2c=` だった例があり、
M5Stack のユニットは版によって引数の形式が変わるため。

---

## 3. セットアップ（最初の1回）

### 3-1. Wi-Fi情報を書く

```
cp secrets.py.example secrets.py
# secrets.py を編集してSSIDとパスワードを記入
```

`secrets.py` は `.gitignore` で除外されるのでGitには入らない。
`deploy.py` が各デバイスへ転送する。

必要なもの: Python 3 + `pyserial`、`esptool`。

### 3-2. StickC に書き込む

USBで1台ずつ接続して実行する。

```
python3 deploy.py
```

工場出荷状態の新品なら、先に「付録A: 工場出荷状態から UIFlow2 へ」を実施する。

### 3-3. M5Go に書き込む

USBで接続して実行する。ToFユニットは **Port A**（本体上部の赤いGroveコネクタ）へ。

```
python3 deploy_tof.py
```

`tof_server.py` と `secrets.py` を書き込み、`boot_option=0` を設定して再起動し、
起動ログを表示する。以後は電源投入だけで動く。

書き込まずに動作だけ試すなら `--run`（20秒間RAM実行）。

**複数のM5Stack機器が繋がっていても自動でM5Goを選ぶ。**
各ポートの `os.uname().machine` を読んで判別するため、
**判別の過程で他の機器（StickC等）もリセットされる**点に注意。
動作中の機器を止めたくないときは `--port` で明示指定する。

```
python3 deploy_tof.py --list                        # 接続機器を判別して一覧
python3 deploy_tof.py --port /dev/cu.usbserial-XXXX # ポート指定
```

---

## 4. 使い方

### 4-1. 自動（本来の用途）

電源を入れるだけ。M5Go が障害物を検知すると StickC が震える。

### 4-2. PC から手動で振動させる

```
python3 vibe.py --scan              # LANを探索して機体を見つける
python3 vibe.py --list              # 一覧
python3 vibe.py --id 1 800          # id=1 を800ms
python3 vibe.py --name stick2 500   # 名前で指定
python3 vibe.py --id 1,2 500        # 複数指定
python3 vibe.py --all 300           # 全機体を同時に
python3 vibe.py --ip 192.168.11.3 500   # 探索せず直接指定
```

`--all` と複数指定は**同時に送信**する（順番に送ると機体ごとに振動がずれる）。
IPはキャッシュ（`.devices_cache.json`）に保存され、応答しなければ自動で再探索する。

### キーを押している間だけ震わせる（`vibe_hold.py`）

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

#### 振動のさせ方が2通りある（起動時に機体ごとに自動判定）

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

#### キーの押し下げ／離しの取り方も2通り

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


### 機体を追加する

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

## 5. M5Go + ToF の詳細

### 実測で確定した VL53L0X の仕様（2026-09-09）

| 項目 | 値 |
|---|---|
| 初期化 | `ToFUnit(i2c=i2c0)` ※ENVユニットと同じ。`port=` は不可 |
| 接続 | Port A（SDA=G21 / SCL=G22）、I2Cアドレス `0x29` |
| 読み取り | `get_distance()` → **float、単位 cm** |
| 測定不能 | **`-0.1`** を返す（「遠すぎる」とエラーの区別はつかない） |
| **実用限界** | **約1m**（カタログ値2mに対して半分） |

### 距離ごとの実測

| 実距離 | 既定設定 | 調整後 |
|---|---|---|
| 10cm | 8.1〜9.0 | — |
| 30cm | 32.2〜34.6 | — |
| 50cm | 56.2〜62.7（ばらつき6.5） | — |
| 100cm | 8/10成功、90〜118（ばらつき27） | **9/10成功、101〜103（ばらつき2.2）** |
| 150cm | 0/10 全滅 | **0/10 全滅** |

### 設定調整は必須

```python
tof.set_measurement_timing_budget(300000)   # 既定 34,433
tof.set_signal_rate_limit(0.05)             # 既定 0.25
```

既定のままだと1mで2割が測定失敗し、±14cm ばらつく。上記でばらつきが **27cm → 2.2cm** に改善した。
ただし**到達距離そのものは伸びない**（1.5mはどの設定でも測定不能）。
測定1回あたり約0.3秒かかるようになる点に注意。


### StickC の自動探索（IPを書かない）

M5Go は起動時に **UDPブロードキャストで StickC を探す**ので、
コードにIPを書く必要がなく、AP側のDHCP予約も不要。

```
M5Go ──[UDP "YUISHIRUBE?" → 192.168.11.255:9999]──> StickC 全台
StickC ──[UDP "YUISHIRUBE <MAC> <IP>"]──> M5Go
```

通知に失敗すると1度だけ再探索するので、StickCが再起動してIPが変わっても追従する。

**宛先は `255.255.255.255` ではなくサブネットブロードキャスト（`192.168.11.255`）**。
実測で `255.255.255.255` は macOS から1台も応答が返らなかった。
M5Goは自分のIPからサブネットを計算するので、別のネットワークでもそのまま動く。

特定の機体だけを鳴らしたいときは `VIBE_MAC` にMACを書く。
空だと最初に応答した1台になるため、**起動のたびに対象が変わり得る**。


### 設計上の注意

#### `-0.1` を必ず先に弾く

「値が小さいほど近い」と素直に書くと、**測定不能の -0.1 が閾値を下回って誤発報する**。
`read_distance()` で `d <= 0` を None にしてから判定している。

#### 発報の繰り返し方は `REPEAT_WHILE_NEAR` で切り替える

| 値 | 動作 | 実測 |
|---|---|---|
| **`True`（現在）** | 警告圏内にある間 `COOLDOWN_S` ごとに鳴り続ける | 20秒で10回 |
| `False` | 一度鳴ったら `CLEAR_CM` より離れるまで黙る | 45秒で3回（近づくたび1回） |

「まだそこにある」ことを知らせ続けたいなら `True`、
置きっぱなしの物に鳴り続けるのが煩わしいなら `False`。

`False` のときの復帰判定を `WARN_CM`(80cm) ではなく `CLEAR_CM`(95cm) にしてあるのは
ヒステリシス。同じ値だと境界のばらつきで鳴ったり止まったりを繰り返す。


### パラメータ

| 定数 | 既定 | 意味 |
|---|---|---|
| `WARN_CM` | 80.0 | この距離以下で警告 |
| `WARN_NEAR_CM` | 40.0 | この距離以下は強く振動(600ms) |
| `CLEAR_CM` | 95.0 | ここまで離れたら再発報できる状態に戻る |
| `NEED_HITS` | 2 | 発報に必要な連続回数 |
| `COOLDOWN_S` | 2.0 | 繰り返し発報の間隔 |
| `REPEAT_WHILE_NEAR` | True | Trueで鳴り続ける／Falseで離れるまで黙る |
| `VIBE_IP` | `""` | StickCのIP。空なら画面表示のみ |


### 用途の前提

**歩行速度1.3m/sだと1mは約0.8秒前**でしかなく、測定に0.3秒かかるため実質0.5秒。
屋外での通常歩行には余裕がない。**屋内・低速移動・着座支援**を前提とする。

より長い距離が要るなら **ToF4M（VL53L1X、公称4m）** への変更が必要。
同じI2C・同じPort Aなので、センサ差し替えとクラス名変更で移行できる。


---

## 6. トラブルシューティング

### つながらないときの切り分け

1. **APは2.4GHzか** — ESP32は5GHz非対応。Buffalo機はSSIDの `-G-` が2.4GHz、`-A-` が5GHz
2. **`python3 vibe.py --scan`** — 機体が見つかるか。見つからなければデバイス側の問題
3. **クライアント間通信が許可されているか** — プライバシーセパレータ / AP isolation をオフ
4. **WPA3専用になっていないか** — WPA2-PSK にする
5. デバイスの画面に出るIPと、`--scan` の結果が一致しているか
6. バンドステアリング（2.4/5GHzで同じSSID）は避ける


### ハマった点（重要）

#### 1. boot_option を 0 にしないと main.py が動かない

UIFlow2 の `boot.py` は `boot_option` が既定値の 1（スタートアップメニュー）のとき
**main.py を実行しない**。書き込みが成功していても起動時に何も起きない。
`deploy.py` が `boot_option = 0` を設定するので通常は意識不要。

#### 2. 学内プロキシで PC からのリクエストが届かない

macOS にシステムプロキシ `proxy.example.ac.jp:8080` が設定されており、
**urllib はこれを自動的に使う**。StickC はLAN内の機器なのでプロキシ経由では届かず
タイムアウトする。`vibe.py` は空の `ProxyHandler` で明示的に迂回している。

curl は macOS のシステムプロキシを読まないため、**curl では成功するのに
Pythonスクリプトだけ失敗する**という紛らわしい症状になる。

```
scutil --proxy
python3 -c "import urllib.request as u; print(u.getproxies())"
```

#### 3. シリアルポートを開くとデバイスがリセットされる

pyserial でポートを開閉すると DTR/RTS がトグルして ESP32 がリセットする。
動作中のサーバを観測しようとしてシリアルを開くと、その瞬間に再起動が始まり
「サーバが応答しない」ように見える。**ネットワーク経由の動作確認中はシリアルを開かないこと。**

#### 4. 電源については問題なし

Wi-Fi接続中に1500ms振動させてもブラウンアウト・リセットは発生しなかった。

#### 5. バッテリー駆動も確認済み（2026-09-09）

StickC 2台ともUSBを抜いた状態で、Wi-Fi接続・HTTP待受・振動すべて正常だった。
`GPIO4` を HIGH に保つ処理（`vibe_server.py` 冒頭）が効いている。
この1行が無いとUSBを抜いた瞬間に電源が落ちる。

#### 6. 5GHz/2.4GHz の混在に注意

Buffalo機はSSIDが `-G-`(2.4GHz) と `-A-`(5GHz) に分かれる。
**PCが5GHz側にいるとESP32機器と通信できない**（同じ192.168.11.xでもARPが通らず
`arp -an` で `(incomplete)` になる）。実際にこれで30分ほど誤診した。

```
system_profiler SPAirPortDataType | grep Channel     # PCの帯域を確認
```

**操作するPC・スマホも必ず2.4GHz側（Buffalo-G-…）に接続すること。**


---

## 7. 動作確認の記録

### 2026-09-08 時点

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


### バッテリー駆動・電源断からの復帰（2026-09-09）

| 時刻 | イベント |
|---|---|
| 11:19:19 | 電源OFFを検知（ネットワークから消失） |
| 11:23:52 | 復帰を検知（`192.168.11.3` で応答） |
| — | 振動 800ms 成功 |

USBを抜いた状態で、Wi-Fi接続・HTTP待受・振動すべて正常。
電源を完全に切ってから入れ直しても自動起動する。

---

## 付録A: 工場出荷状態から UIFlow2 へ

新品の M5StickC Plus2 には Arduino製の工場デモが入っており、**MicroPython が無い**ため
`deploy.py` は使えない。まず UIFlow2 を書き込む。

工場デモが入っているかは、起動メッセージで判別できる。

```
board: 5
normal mode
mic init ok
imu test
```

### M5Burner は使えない（このMacでは）

`/Applications/M5Burner.app` (v3.0.0) はインストール済みだが機能しない。

- アプリが API を `http://m5burner-api.m5stack.com`（平文HTTP / **port 80**）で
  ハードコードしているが、**現在 port 80 は閉じており 443 のみ開いている**。
  そのためファームウェア一覧が永久に空になり、書き込み対象を選べない
- 代替ホスト（`m5burner-api-fc-hk-cdn`）も port 80 は閉じている
- 加えて x86_64 のみ・コード署名が一切無く Gatekeeper にも弾かれる

**代わりに esptool を直接使う。** 以下は検証済みの手順。

### 手順

#### 1. ポートとチップを確認

```
ls /dev/cu.usbserial-*
esptool.py --port /dev/cu.usbserial-XXXX --no-stub flash_id
```

`ESP32-PICO-V3-02` / `Detected flash size: 8MB` なら StickC Plus2。

#### 2. ファームウェアのカタログを取得

```
curl -s -o catalog.json https://m5burner-api.m5stack.com/api/firmware
```

認証不要の公開API。約2500件のJSON配列が返る。

#### 3. 該当ファームウェアを探す

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

#### 4. bin を取得して検証

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

#### 5. 消去して書き込む

```
esptool.py --port /dev/cu.usbserial-XXXX --chip esp32 --baud 115200 erase-flash
esptool.py --port /dev/cu.usbserial-XXXX --chip esp32 --baud 115200 \
    write-flash --flash-size keep 0x0 fw.bin
```

`Hash of data verified.` が出れば成功。所要時間は StickC Plus2 (8MB) で約6分、
M5Go (16MB) で約5分半。

**ボーレートは 115200 にすること。** このUSBシリアル変換は 460800 / 921600 では
read-flash が途中で切れる（`Serial data stream stopped`）。

#### 6. 確認

```
python3 deploy.py --whoami
```

MAC が表示されれば MicroPython が動いている。


---

## 付録B: AIカメラ（UnitV2）を見送った理由

参考として実測結果を残す。UnitV2 は HTTP で操作でき、UART配線は不要だった
（`POST /func` で機能切替、`POST /func/result` で結果取得、`/video_feed` でMJPEG）。

| 問題 | 実測 |
|---|---|
| 信頼度が正しさを表さない | 画面に人がいないのに `person` が prob 0.78 |
| 未学習物体は原理的に検出不可 | ダンボール箱は80クラスに該当なし。`suitcase` に9%だけ反応 |
| 背もたれのない椅子も検出困難 | 丸椅子は `frisbee` と誤検出された |
| 近すぎると検出率が下がる | 椅子が画面に収まらないと認識率が落ちる |

唯一使えそうだったのは**出現頻度**。背もたれ椅子が正面にあると `chair` が43%、
無いと3%で、約14倍の差があった。1フレームでの判定は不可、時間方向の多数決が必須。


---

## 付録C: ファイル一覧

| ファイル | 役割 |
|---|---|
| `tof_server.py` | **M5Go本体側。ToFで障害物を検知しStickCに通知する** |
| `vibe_server.py` | **StickC本体側。全機体共通。`/vibe` `/hold` `/off` `/whoami` とUDP探索応答** |
| `devices.py` | 台帳（PC側のみ）。MAC→名前。編集しても再書き込み不要 |
| `vibe.py` | PC側。探索・キャッシュ・振動指示 |
| `vibe_hold.py` | PC側。キーを押している間だけ震わせる |
| `deploy.py` | `vibe_server.py` を **StickC** に書き込む |
| `deploy_tof.py` | `tof_server.py` を **M5Go** に書き込む |
| `find_vibe_pin.py` | 振動ピン特定用（記録。通常は不要） |
| `secrets.py` | Wi-Fi認証情報。**Git除外**。`secrets.py.example` からコピーして作る |
| `.devices_cache.json` | 探索結果のキャッシュ（自動生成、Git除外） |

## 付録D: 補足

- 振動時間は安全のため **最大3秒** に制限している（`MAX_MS`）
- 周囲のAPスキャンでは ch1/4/6/9/11 が使用中。ch9 に強いAPがあるため、
  反応が不安定なら AP のチャンネルを ch1 か ch6 に手動設定する
- Wi-Fiパスワードは `secrets.py` に分離済み（`.gitignore` で除外）。
  ただし**デバイスのフラッシュ上には平文で保存される**ため、機体を貸し出す際は注意
