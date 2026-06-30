// ElderCare AI — Smart Elderly Care, MCU half (UNO Q STM32 microcontroller).
//
// Real-time I/O shim built on Modulino (QWIIC/I2C) modules + one servo:
//   - Modulino Pixels  : 8-LED face-detection progress bar (driven from Python)
//   - Modulino Buzzer  : confirm beep (pill) + emergency alarm
//   - Modulino Thermo  : ambient temperature / humidity
//   - Modulino Buttons : A/B/C dispense medication channels A/B/C
//   - Servos (pins 9/10/11) : three pill dispensers ("ปัดยาลงมา")
//
// All decision logic lives on the Python brain; this side just exposes the
// hardware over the Bridge. Modulinos share the QWIIC bus — no pin wiring.
//
// Bridge contract (kept in lockstep with python/sensors.py):
//   actuators (Python -> MCU):
//     set_led(bool)                 on-board heartbeat LED (liveness)
//     pixels_progress(int count)    light count/8 pixels (face-detect status)
//     buzzer_beep(int freq,int ms)  one short tone (pill confirm / feedback)
//     buzzer_alarm(bool on)         repeating emergency tone
//     dispense_pill(int channel) -> bool  sweep one dispenser servo (0=A pin9, 1=B pin10)
//   sensors (Python polls MCU):
//     read_temperature() -> float   ambient °C   (Thermo)
//     read_humidity()    -> float   ambient %RH  (Thermo)
//     get_and_clear_button(int idx) -> bool  latched press, idx 0=A 1=B 2=C

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>

ModulinoBuzzer  buzzer;
ModulinoThermo  thermo;
ModulinoPixels  pixels;
ModulinoButtons buttons;

// Three independent pill-dispenser channels (one servo each).
static const int PIN_SERVO_A = 9;    // medication channel A (button A)
static const int PIN_SERVO_B = 10;   // medication channel B (button B)
static const int PIN_SERVO_C = 11;   // medication channel C (button C)
static const int NUM_PIXELS  = 8;

// --- pill dispenser servos (software PWM) -------------------------------
// The Servo library isn't available on the UNO Q Zephyr core, so we bit-bang
// the standard ~50 Hz hobby-servo pulse train ourselves. Pulse width sets the
// angle: ~600 µs ≈ 0°, ~2400 µs ≈ 180°.
static const int SERVO_REST_US     = 600;    // arm at rest (position 0)
static const int SERVO_DISPENSE_US = 1700;   // arm swept out (~110°)
static const int SERVO_FRAME_MS    = 18;     // ~50 Hz refresh

void servoHold(int pin, int pulseUs, int frames) {
  for (int i = 0; i < frames; i++) {
    digitalWrite(pin, HIGH);
    delayMicroseconds(pulseUs);
    digitalWrite(pin, LOW);
    delay(SERVO_FRAME_MS);
  }
}

// --- emergency alarm (re-triggered tone so it sustains) -----------------
bool alarmOn = false;
unsigned long lastAlarmBeep = 0;
const unsigned long ALARM_PERIOD_MS = 600;

// --- latched button presses (cleared when Python reads) -----------------
volatile bool btnLatched[3] = {false, false, false};

// --- cached Thermo reads (don't poll I2C on every Bridge call) ----------
float cachedTempC = NAN;
float cachedHum   = NAN;
unsigned long lastThermoMs = 0;
const unsigned long THERMO_PERIOD_MS = 2000;

// --- actuators -----------------------------------------------------------
void set_led(bool on) {
  digitalWrite(LED_BUILTIN, on ? HIGH : LOW);
}

void pixels_progress(int count) {
  if (count < 0) count = 0;
  if (count > NUM_PIXELS) count = NUM_PIXELS;
  pixels.clear();
  // Filling up = counting toward the 5 s hold; full bar (8) = confirmed.
  ModulinoColor c = (count >= NUM_PIXELS) ? GREEN : BLUE;
  for (int i = 0; i < count; i++) {
    pixels.set(i, c, 60);   // brightness 0..100
  }
  pixels.show();
}

void buzzer_beep(int freq, int ms) {
  buzzer.tone(freq, ms);
}

void buzzer_alarm(bool on) {
  alarmOn = on;
  if (!on) {
    buzzer.noTone();
  }
}

bool dispense_pill(int channel) {
  // One sweep of the selected channel's arm to push a dose down, back to rest.
  int pin = PIN_SERVO_A;
  if (channel == 1) pin = PIN_SERVO_B;
  else if (channel == 2) pin = PIN_SERVO_C;
  servoHold(pin, SERVO_DISPENSE_US, 25);  // ~450 ms out
  servoHold(pin, SERVO_REST_US, 12);      // back to rest (position 0)
  return true;
}

// --- sensors -------------------------------------------------------------
float read_temperature() {
  return isnan(cachedTempC) ? -127.0f : cachedTempC;
}

float read_humidity() {
  return isnan(cachedHum) ? -1.0f : cachedHum;
}

bool get_and_clear_button(int idx) {
  if (idx < 0 || idx > 2) return false;
  bool v = btnLatched[idx];
  btnLatched[idx] = false;
  return v;
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);

  Modulino.begin();
  buzzer.begin();
  thermo.begin();
  pixels.begin();
  buttons.begin();
  buttons.setLeds(true, true, true);     // light all three dispense buttons
  pixels.clear();
  pixels.show();

  pinMode(PIN_SERVO_A, OUTPUT);
  pinMode(PIN_SERVO_B, OUTPUT);
  pinMode(PIN_SERVO_C, OUTPUT);
  digitalWrite(PIN_SERVO_A, LOW);
  digitalWrite(PIN_SERVO_B, LOW);
  digitalWrite(PIN_SERVO_C, LOW);
  // On startup drive all dispenser servos to position 0 (rest) and hold long
  // enough (~500 ms) for them to physically reach there before anything else.
  servoHold(PIN_SERVO_A, SERVO_REST_US, 28);
  servoHold(PIN_SERVO_B, SERVO_REST_US, 28);
  servoHold(PIN_SERVO_C, SERVO_REST_US, 28);

  Bridge.begin();
  Bridge.provide("set_led", set_led);
  Bridge.provide("pixels_progress", pixels_progress);
  Bridge.provide("buzzer_beep", buzzer_beep);
  Bridge.provide("buzzer_alarm", buzzer_alarm);
  Bridge.provide("dispense_pill", dispense_pill);
  Bridge.provide("read_temperature", read_temperature);
  Bridge.provide("read_humidity", read_humidity);
  Bridge.provide("get_and_clear_button", get_and_clear_button);
}

void loop() {
  unsigned long now = millis();

  // Refresh Thermo on its own cadence so Bridge reads never wait on I2C.
  if (now - lastThermoMs >= THERMO_PERIOD_MS) {
    lastThermoMs = now;
    float t = thermo.getTemperature();
    float h = thermo.getHumidity();
    if (!isnan(t)) cachedTempC = t;
    if (!isnan(h)) cachedHum = h;
  }

  // Latch any button press; Python clears it on read.
  if (buttons.update()) {
    for (int i = 0; i < 3; i++) {
      if (buttons.isPressed(i)) btnLatched[i] = true;
    }
  }

  // Sustain the emergency tone while the alarm is active.
  if (alarmOn && (now - lastAlarmBeep >= ALARM_PERIOD_MS)) {
    lastAlarmBeep = now;
    buzzer.tone(2200, 300);
  }
}
