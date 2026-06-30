# ElderCare AI — ระบบดูแลผู้สูงอายุอัจฉริยะ (Smart Elderly Care)

แอป [Arduino App Lab](https://docs.arduino.cc/software/app-lab/) สำหรับ **Arduino UNO Q**
ที่ผสาน **AI + IoT + Sensor + Cloud + Data Analytics** เข้าด้วยกัน ตามแนวคิด
**Smart · Green · Safe · Creative**

UNO Q มีสองสมอง โปรเจกต์นี้แบ่งงานให้ตรงกับฮาร์ดแวร์:

- **Python** (`python/`) รันบน Qualcomm Linux (MPU) — เป็น "สมอง AI"
- **C++ sketch** (`sketch/`) รันบน STM32 (MCU) — เป็น "ตัวจัดการเซนเซอร์/อุปกรณ์แบบเรียลไทม์"

ทั้งสองฝั่งคุยกันผ่าน **Bridge** RPC (sketch `Bridge.provide(...)` ↔ Python `Bridge.call(...)`).

## ฟีเจอร์ตามแนวคิด 4 ด้าน

| ด้าน | สิ่งที่ทำ | ไฟล์ |
|------|-----------|------|
| **Smart** | ตรวจจับใบหน้า (OpenCV Haar) + **ระบุตัวตน** (LBPH) + วิดีโอสดบนเว็บ — เห็นใบหน้าครบ 5 วิ → จ่ายยา | `python/face_detection.py`, `python/face_db.py` |
| **IoT** | Modulino (QWIIC/I2C): Thermo, Pixels, Buzzer, Buttons + เซอร์โวจ่ายยา | `sketch/sketch.ino`, `python/sensors.py` |
| **Safe** | Push Notification (ntfy/Telegram/webhook) + บัซเซอร์ฉุกเฉิน + ปุ่ม SOS | `python/notifier.py` |
| **Green** | บันทึกข้อมูลดิจิทัล 100% (ไม่ใช้กระดาษ) ลง SQLite + มิเรอร์ขึ้นคลาวด์ | `python/database.py` |
| **Data Analytics** | ประเมินความเสี่ยง (0–100), ตารางยา, เฝ้าระวังการนิ่ง (ออปชัน) | `python/analytics.py` |
| **Creative** | ผู้ช่วยเสียง (TTS) + **chatbot z.ai (GLM)** + เครื่องจ่ายยายืนยันด้วยใบหน้า + แดชบอร์ด | `python/voice.py`, `python/chatbot.py`, `python/dashboard.py` |

### การทำงานหลัก (Face-confirmed pill dispenser)

1. กล้องจับใบหน้าแบบเรียลไทม์ → **Modulino Pixels** ไล่ติดทีละดวงเป็น progress bar ของ 5 วินาที
2. เมื่อใบหน้าอยู่ในเฟรมครบ **5 วิ** → **Modulino Buzzer** ดังยืนยัน + **เซอร์โวปัดยาลงมา**
3. ใบหน้าต้องออกจากเฟรมก่อน ระบบจึงจะ re-arm รอบถัดไป (กันจ่ายซ้ำ)
4. **Buttons**: A / B / C = จ่ายยาช่อง A / B / C ทันที (SOS + รับทราบ ย้ายไปบนแดชบอร์ด)

## โครงสร้างโค้ด

```
app.yaml                 manifest + bricks (web_ui)
assets/
  index.html             แดชบอร์ดผู้ดูแล (web_ui brick เสิร์ฟที่ :7000, poll /api/state ทุก 1 วิ)
python/
  main.py                ตัวประสานงานหลัก (สร้างเธรด: heartbeat / sensor / watch)
  config.py              ค่าคอนฟิกทั้งหมด (อ่านจาก environment)
  face_detection.py      ตรวจจับใบหน้า + ระบุตัวตน + วาดกรอบ + สตรีม JPEG + logic 5 วิ
  face_db.py             ฐานข้อมูลใบหน้า (LBPH) — เทรน/จดจำ/ลงทะเบียน
  faces/<ชื่อคน>/*.jpg   รูปลงทะเบียนใบหน้า (สร้างอัตโนมัติเมื่อลงทะเบียนผ่านเว็บ)
  fall_detection.py      AI ตรวจจับการล้ม (parked — เผื่ออยากใช้ pose ภายหลัง)
  sensors.py             facade ครอบ Bridge.call (สัญญา RPC ฝั่ง Python)
  analytics.py           คะแนนความเสี่ยง + ตารางยา + เฝ้าระวังการนิ่ง
  notifier.py            push notification หลายช่องทาง
  database.py            SQLite + มิเรอร์คลาวด์
  voice.py               ผู้ช่วยเสียงออฟไลน์ (pyttsx3)
  dashboard.py           แดชบอร์ดผ่าน web_ui brick
  requirements.txt       ไลบรารี Python
sketch/
  sketch.ino             เซนเซอร์/อุปกรณ์ฝั่ง MCU
  sketch.yaml            build profile (arduino:zephyr)
```

## Bricks ที่ใช้ (`app.yaml`)

| Brick | ใช้ทำอะไร |
|-------|-----------|
| `arduino:web_ui` | แดชบอร์ดสำหรับผู้ดูแล — แสดงสถานะสด, ปุ่มรับทราบเหตุ (ack), สั่งจ่ายยา, ยืนยันทานยา |

## ไลบรารีที่ต้องติดตั้ง

**Python (`python/requirements.txt`)** — App Lab ติดตั้งให้อัตโนมัติตอน deploy:

- `numpy` — จัดการ array (label/เฟรม)
- **OpenCV (`cv2`)** — มากับ Arduino runtime อยู่แล้ว (camera peripheral ใช้) จึง **ไม่ pin ใน requirements** เพื่อเลี่ยง build ซ้ำซ้อน
- ตรวจจับใบหน้าใช้ **Haar cascade ที่มากับ base cv2** — ไม่ต้องลง mediapipe/โมเดลเพิ่ม

> **ระบุตัวตน (LBPH)** ต้องการ `cv2.face` จาก `opencv-contrib` — ถ้าบอร์ดลง contrib ได้ ให้ uncomment
> `opencv-contrib-python-headless` ใน `requirements.txt`; ถ้าลงไม่ได้ ระบบยังทำงาน (วิดีโอสด + ตรวจจับใบหน้า)
> เพียงแต่จะขึ้น "ไม่รู้จัก" แทนชื่อ
- `requests` — push notification + มิเรอร์ข้อมูลขึ้นคลาวด์
- `pyttsx3` — ผู้ช่วยเสียงออฟไลน์ (ใช้ espeak-ng เป็น backend)

**Arduino libraries (sketch)** — ติดตั้งผ่าน Library Manager / `arduino-cli lib install`:

- `Arduino_RouterBridge` — Bridge RPC ระหว่างสองสมอง (มากับ App Lab)
- `Arduino_Modulino` — ไลบรารีตัวเดียวครอบทุกโมดูล (Buzzer / Thermo / Pixels / Buttons), `#include <Arduino_Modulino.h>`

> เซอร์โวจ่ายยา **ไม่ใช้ไลบรารี `Servo`** (ไม่มีบน UNO Q Zephyr core) — sketch สร้าง
> สัญญาณ ~50 Hz เองด้วยการ bit-bang ขา (ฟังก์ชัน `servoHold`)
>
> หมายเหตุ: sketch รันบน core `arduino:zephyr` (ไม่ใช่ AVR) — ทดสอบกับ
> `Arduino_Modulino` 0.9.0 และเช็กชื่อเมธอด
> (`getTemperature`, `pixels.set/show`, `buttons.isPressed`, `buzzer.tone`) ให้ตรงกับเวอร์ชันจริง

## การเชื่อมต่อฮาร์ดแวร์

Modulino ทุกตัวต่อพ่วงกันบนสาย **QWIIC/I2C** เส้นเดียว (ไม่ต้องเดินสาย pin):

| อุปกรณ์ | การต่อ | หน้าที่ |
|---------|--------|---------|
| Modulino **Thermo** | QWIIC | อุณหภูมิ/ความชื้นห้อง (cache ทุก 2 วิ) |
| Modulino **Pixels** | QWIIC | progress bar การตรวจจับใบหน้า (8 ดวง) |
| Modulino **Buzzer** | QWIIC | beep ยืนยันจ่ายยา + เสียงฉุกเฉิน |
| Modulino **Buttons** | QWIIC | A/B/C = จ่ายยาช่อง A/B/C |
| เซอร์โวจ่ายยา A | pin **9** | ยาช่อง A — ปัดลงมา 1 ครั้งต่อโดส |
| เซอร์โวจ่ายยา B | pin **10** | ยาช่อง B — ปัดลงมา 1 ครั้งต่อโดส |
| เซอร์โวจ่ายยา C | pin **11** | ยาช่อง C — ปัดลงมา 1 ครั้งต่อโดส |
| กล้อง (USB/CSI) | ฝั่ง Linux | `CARE_CAMERA_INDEX` |
| LED บนบอร์ด | `LED_BUILTIN` | heartbeat (เช็กว่า Bridge ยังเชื่อมกัน) |

## สัญญา Bridge (ต้องตรงกันสองฝั่ง)

| ชื่อ RPC | ทิศทาง | ลายเซ็น |
|----------|--------|---------|
| `set_led` | Py→MCU | `(bool)` ไฟ heartbeat |
| `pixels_progress` | Py→MCU | `(int count)` ติด count/8 ดวง |
| `buzzer_beep` | Py→MCU | `(int freq, int ms)` เสียงสั้น |
| `buzzer_alarm` | Py→MCU | `(bool)` เสียงฉุกเฉินต่อเนื่อง |
| `dispense_pill` | Py→MCU | `(int channel) -> bool` ปัดยา (0=A พิน9, 1=B พิน10, 2=C พิน11) |
| `read_temperature` | MCU→Py | `() -> float` °C |
| `read_humidity` | MCU→Py | `() -> float` %RH |
| `get_and_clear_button` | MCU→Py | `(int idx) -> bool` (latched, 0=A 1=B 2=C) |

## กล้อง · ระบุตัวตน · แดชบอร์ด

แดชบอร์ดที่ `http://<board-ip>:7000` มี **วิดีโอสด** พร้อมกรอบตรวจจับใบหน้า
(เขียว = รู้จัก, ส้ม = ไม่รู้จัก) และป้ายชื่อผู้สูงอายุที่ระบุตัวตนได้

> **กล้องต้องเข้าถึงผ่าน Arduino camera peripheral** ไม่ใช่ `cv2.VideoCapture` ตรงๆ
> (คอนเทนเนอร์ Python มองไม่เห็น `/dev/video*` เอง) — `face_detection.py` ใช้
> `from arduino.app_peripherals.camera import Camera` แล้ว `cam.start()` / `cam.capture()`
> เปลี่ยนกล้องได้ด้วย `CARE_CAMERA_INDEX` (เช่น `0`, `usb:0`, `csi:0`)

REST endpoints (ฝั่ง `dashboard.py` ด้วย `expose_api`):

| Endpoint | ใช้ทำอะไร |
|----------|-----------|
| `GET /api/state` | สถานะสด (อุณหภูมิ/ใบหน้า/ตัวตน/ความเสี่ยง/เหตุการณ์) — poll ทุก 1 วิ |
| `GET /video` | **วิดีโอสด MJPEG** (multipart, connection เดียว, 30fps) ใส่ `<img src="/video">` |
| `GET /api/frame` | เฟรมเดียวเป็น JPEG base64 — fallback ถ้า MJPEG ใช้ไม่ได้ |
| `GET /api/enroll?name=...` | ลงทะเบียนใบหน้าปัจจุบัน (เว้น `name` = ใช้ `CARE_PERSON_NAME`) |
| `GET /api/chat?q=...` | ส่งข้อความหา chatbot z.ai → `{reply}` |
| `GET /api/sos` · `/api/ack` | แจ้งเหตุฉุกเฉิน / รับทราบ-หยุดสัญญาณ |
| `GET /api/dispense_a` · `/api/dispense_b` · `/api/dispense_c` · `/api/med_taken` | จ่ายยาแต่ละช่อง / ยืนยันทานยา |

### วิธีลงทะเบียนใบหน้า (ระบุตัวตน)

1. เปิดแดชบอร์ด → ให้ผู้สูงอายุหันหน้าเข้ากล้อง
2. พิมพ์ชื่อ (หรือเว้นว่างให้ใช้ค่าเริ่มต้น) แล้วกด **“บันทึกใบหน้าปัจจุบัน”** ซ้ำ **5–10 ครั้ง** จากหลายมุม/แสง
3. ระบบเทรน LBPH ใหม่อัตโนมัติ หลังจากนั้นป้ายจะขึ้นชื่อเมื่อจำได้
4. หรือก็อปรูปไปวางเองที่ `python/faces/<ชื่อคน>/*.jpg` แล้วรีสตาร์ทแอป

> ตั้ง `CARE_DISPENSE_REQUIRE_KNOWN=true` เพื่อให้ **จ่ายยาเฉพาะคนที่ระบบรู้จัก** (กันจ่ายให้คนแปลกหน้า)
> ข้อมูลใบหน้าทั้งหมดอยู่บนบอร์ด ไม่ส่งขึ้นคลาวด์ (รักษาความเป็นส่วนตัว/จริยธรรม AI)

## Chatbot (z.ai / Zhipu GLM)

แดชบอร์ดมีกล่องแชต — คุยกับผู้ช่วย AI (ตอบเรื่องสุขภาพเบื้องต้น/ยา/ทั่วไป และรู้สถานะปัจจุบัน
เช่น อุณหภูมิห้อง คะแนนเสี่ยง ตารางยา) ขับเคลื่อนด้วย z.ai GLM (API แบบ OpenAI-compatible)

```bash
export ZAI_API_KEY="ใส่ key ของคุณ"      # ต้องมี key แชตถึงทำงาน
export ZAI_MODEL="glm-4.5-flash"         # (ออปชัน) เปลี่ยนรุ่นได้ เช่น glm-4.6
export ZAI_BASE_URL="https://api.z.ai/api/paas/v4"   # (ออปชัน)
```

> ถ้าไม่ตั้ง `ZAI_API_KEY` แชตจะปิดอยู่ (ส่วนอื่นทำงานปกติ) — `chatbot.py` ใช้ `requests` เรียก
> `{base}/chat/completions` ไม่มี dependency เพิ่ม

## คอนฟิก (environment variables)

ตั้งค่าก่อนรัน เพื่อเปิดใช้แจ้งเตือน/คลาวด์ (ค่าดีฟอลต์รันได้เลยสำหรับเดโม):

```bash
export CARE_PERSON_NAME="คุณยายสมศรี"
export CARE_NTFY_TOPIC="depa-care-แบบสุ่ม-1234"     # subscribe ในแอป ntfy บนมือถือผู้ดูแล
export CARE_MED_TIMES="08:00@A,12:00@B,18:00@C"     # ตารางยา (@A/@B/@C = เลือกช่องเซอร์โว, ไม่ใส่ = A)
export ZAI_API_KEY="..."                            # เปิด chatbot
export CARE_CLOUD_URL="https://xxx.firebaseio.com/events.json"  # (ออปชัน) มิเรอร์ขึ้นคลาวด์
```

ดูตัวแปรทั้งหมดได้ใน `python/config.py`

## รัน (บน UNO Q)

```bash
arduino-app-cli app start .   # build + deploy ทั้งสองฝั่ง แล้วรัน
arduino-app-cli app logs  .   # ดู log
arduino-app-cli app stop  .   # หยุด
```

## วิธีตรวจสอบการทำงาน

- LED heartbeat บนบอร์ดกระพริบ = ระบบ Python ↔ MCU เชื่อมกันได้
- เอาหน้าเข้าเฟรมกล้อง → Pixels ไล่ติดทีละดวง; ค้างครบ 5 วิ → Buzzer ดัง + เซอร์โวปัดยา
- เอาหน้าออกจากเฟรม แล้วกลับเข้ามาใหม่ → ระบบ re-arm จ่ายยาได้อีกครั้ง
- กดปุ่ม A (SOS) → เสียงฉุกเฉัน + push แจ้งเตือนผู้ดูแล; กดปุ่ม B เพื่อหยุด
- เปิดแดชบอร์ดที่ `http://<board-ip>:7000` → เห็นสถานะสด (อุณหภูมิ/ใบหน้า/ความเสี่ยง) + ปุ่มสั่งการ (รับทราบ / จ่ายยา / ยืนยันทานยา)
