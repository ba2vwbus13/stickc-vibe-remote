"""ピンごとに振動回数を変えて走査する。ユーザーは回数を数えるだけでよい。
1回=GPIO26, 2回=GPIO0, 3回=GPIO25, 4回=GPIO32, 5回=GPIO33"""
import serial, time, sys, glob

ports = [p for p in glob.glob('/dev/cu.usb*')]
if not ports:
    print("USBシリアルが見つかりません"); sys.exit(1)
PORT = ports[0]
print("PORT:", PORT)

CANDIDATES = [26, 0, 25, 32, 33]

s = serial.Serial(PORT, 115200, timeout=0.2)
def drain(sec):
    t=time.time(); b=b""
    while time.time()-t<sec: b+=s.read(4096)
    return b

ok=False
for _ in range(30):
    s.write(b"\x02\r\x03\x03")
    if drain(0.5).rstrip().endswith(b">>>"): ok=True; break
print("REPL:", ok)
if not ok:
    print(repr(drain(1.0)[-400:])); s.close(); sys.exit(1)
drain(0.3)
s.write(b"\x01"); drain(1.2); drain(0.3)

lines = [
 "import time",
 "from machine import Pin",
 "try:",
 "    Pin(4, Pin.OUT).value(1)",
 "except Exception as e:",
 "    print('GPIO4 NG:', e)",
 "cands = %r" % (CANDIDATES,),
 "time.sleep(2)   # 手に持つ余裕",
 "for i, g in enumerate(cands):",
 "    n = i + 1",
 "    print('>>> %d 回:  GPIO %d' % (n, g))",
 "    try:",
 "        p = Pin(g, Pin.OUT)",
 "        for _ in range(n):",
 "            p.value(1); time.sleep_ms(350)",
 "            p.value(0); time.sleep_ms(250)",
 "    except Exception as e:",
 "        print('    ERROR:', e)",
 "    time.sleep(2.5)",
 "print('=== 走査終了 ===')",
]
script = ("\n".join(lines) + "\n").encode()
for i in range(0, len(script), 256):
    s.write(script[i:i+256]); time.sleep(0.03)
s.write(b"\x04")
print(drain(45.0).decode("utf-8","replace"))
s.write(b"\x02"); drain(0.4); s.close()
