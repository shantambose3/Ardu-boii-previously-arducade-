#include <Wire.h>
#include <Arduino_RouterBridge.h>
#include <MsgPack.h>
#include <U8g2lib.h>

// Forward declarations needed because Arduino auto-generates function
// prototypes above these struct definitions.
struct Vibrator;
struct ControllerState;
struct ControllerStateWire;

#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define OLED_ADDR      0x3C

// U8g2 talks pure I2C via Wire; "F" = full-frame-buffer mode,
// HW_I2C = hardware I2C, U8X8_PIN_NONE = no reset pin wired.
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

#define MPU6050_ADDR  0x68
#define MPU6050_PWR_MGMT_1   0x6B
#define MPU6050_ACCEL_XOUT_H 0x3B

// --- Vibration motors ---
#define VIB_LEFT_PIN   6   // D6
#define VIB_RIGHT_PIN  7   // D7

// --- Direct GPIO controller inputs ---
#define BTN1_PIN   2   // D2 - bomb / menu confirm
#define BTN2_PIN   3   // D3 - infinity ray / menu back
#define BTN3_PIN   4   // D4 - vacuum nails
#define BTN4_PIN   5   // D5 - mjolnir

#define LAYER1_BTN_PIN  8    // D8  - OLED guide: confirm/start
#define LAYER2_BTN_PIN  9    // D9  - OLED guide: page next
#define LAYER3_BTN_PIN  10   // D10 - OLED guide: page back
// NOTE: these three no longer double as Python-side layer-select
// shortcuts (see CHANGELOG.md) -- they only drive the boot-time OLED
// instructions screen below now. layerButtons is still read/sent over
// the Bridge for compatibility, but nothing on the Python side acts
// on it anymore.

#define SLEEP_WAKE_PIN 12   // D12 - pause/play (read in python/main.py)

#define MIC_PIN    A3   // MAX9814 OUT (analog envelope output)

#define JOY_X_PIN  A0
#define JOY_Y_PIN  A1
#define PHOTO_PIN  A2   // photoresistor -- fatigue/difficulty-ease input

struct Vibrator {
  uint8_t pin;
  bool active;
  unsigned long stopAtMs;
};

Vibrator vibL = { VIB_LEFT_PIN, false, 0 };
Vibrator vibR = { VIB_RIGHT_PIN, false, 0 };

void vibeUpdate(Vibrator &v, unsigned long nowMs) {
  if (v.active && (long)(nowMs - v.stopAtMs) >= 0) {
    digitalWrite(v.pin, LOW);
    v.active = false;
  }
}

// Non-blocking: sets the pin HIGH and records a stop time; vibeUpdate()
// clears it once nowMs passes stopAtMs. Retriggering an already-active
// motor just restarts its stop time.
void startVibe(Vibrator &v, unsigned long nowMs, uint16_t durationMs) {
  digitalWrite(v.pin, HIGH);
  v.active = true;
  v.stopAtMs = nowMs + durationMs;
}

struct ControllerState {
  uint8_t buttons;      // bit0=D2, bit1=D3, bit2=D4, bit3=D5
  uint8_t layerButtons; // bit0=D8, bit1=D9, bit2=D10
  bool    sleepWake;    // D12
  int16_t joyX;         // A0
  int16_t joyY;         // A1
  int16_t lightLevel;   // A2
  int16_t micLevel;     // A3
  int16_t accelX;
  int16_t accelY;
  int16_t accelZ;
  bool mpuOk;
};

ControllerState state;
bool oledOk = false; // set in setup(); guards aiRender()
bool oledStatsHidden = false; // toggled by a D12 double-tap, see main.py

// analogRead() returns 0..1023, not centered on 0. Sample the rest
// position once at boot and subtract it every loop so joyX/joyY read
// as a signed value around 0.
int16_t joyXCenter = 512;
int16_t joyYCenter = 512;

// ---- Joystick mounting-rotation correction ----
//
// The joystick module isn't mounted "upright" on this PCB (see the
// board layout) -- it sits rotated relative to how the case is held,
// so the raw A0/A1 (X/Y) pot axes don't line up with the player's
// actual up/down/left/right. Rather than rewire the WASD mapping
// downstream (which both python/main.py AND the network split
// (board_server.py/pc_client.py) would each have to duplicate), we
// correct it once, right here at the source, so every consumer just
// sees an already-correct joyX/joyY.
//
// Set this to whichever matches how the module is actually soldered
// down. Both are a 90-degree swap+flip of the raw X/Y axes -- the
// only two options for a 90-degree mounting rotation:
//   JOY_ROTATE_CW  : corrected_X = -raw_Y,  corrected_Y =  raw_X
//   JOY_ROTATE_CCW : corrected_X =  raw_Y,  corrected_Y = -raw_X
//
// Best guess from the PCB layout is a 90-degree clockwise mount, so
// that's the default below. HOW TO VERIFY / FIX ON HARDWARE: push the
// stick straight up (away from you). If the player ship moves up,
// you're done. If it instead moves right, left, or down, try the
// other setting (flip the #define below) and re-flash -- one of the
// two will be correct, there's no in-between to tune.
#define JOY_ROTATE_CW 1   // 1 = rotated 90 deg clockwise (default guess)
                          // 0 = rotated 90 deg counter-clockwise instead

void applyJoystickRotation(int16_t rawX, int16_t rawY, int16_t &outX, int16_t &outY) {
#if JOY_ROTATE_CW
  outX = -rawY;
  outY = rawX;
#else
  outX = rawY;
  outY = -rawX;
#endif
}

const unsigned long OLED_FRAME_MS = 200;

// ---- OLED: boot-time instructions screen ----
//
// Shown first on power-up, before the AI-learning status panel takes
// over. Paged with D9 (next) / D10 (back); D8 confirms and dismisses
// it for the rest of the session -- there's no auto-timeout, it just
// sits on the last page you left it on until D8 is pressed.
//
// D8/D9/D10 are ONLY this guide now -- they used to double as
// LAYER1/2/3 jump-to-layer shortcuts read via layerButtons
// (LAYER_BUTTON_MAP in python/main.py), but that Python-side handling
// was removed (see CHANGELOG.md) so these three buttons don't fight
// over meaning anymore. loop() still zeroes state.layerButtons while
// this screen is showing, out of caution, but it's effectively a
// no-op now since nothing downstream reads that field.

enum OledScreen { SCREEN_INSTRUCTIONS, SCREEN_AI_STATUS };
OledScreen oledScreen = SCREEN_INSTRUCTIONS;

const char *const INSTRUCTION_PAGES[][4] = {
  { "MOVE & FIRE",   "Joystick: move",   "D2 Bomb   D3 Ray", "D4 Nails  D5 Mjolnir" },
  { "LAYER SELECT",  "Joystick up/down", "then D2 to confirm", ""                    },
  { "THIS SCREEN",   "D9 Next  D10 Back", "D8  Confirm/Start", ""                    },
};
const uint8_t INSTRUCTION_PAGE_COUNT = sizeof(INSTRUCTION_PAGES) / sizeof(INSTRUCTION_PAGES[0]);
uint8_t instructionPage = 0;

// Simple time-gated debounce for the three instruction-nav buttons --
// separate from readLayerButtons()'s raw read, since here we care
// about single clean "presses", not a continuous bitmask.
bool prevD8Pressed = false, prevD9Pressed = false, prevD10Pressed = false;
unsigned long lastInstructionActionMs = 0;
const unsigned long INSTRUCTION_DEBOUNCE_MS = 150;

// Global (not loop()-local) so handleInstructionButtons() can force an
// immediate redraw on page-change/confirm instead of waiting up to
// OLED_FRAME_MS for the next scheduled render.
unsigned long lastOledMs = 0;

// AI status, pushed once per frame from the Python side via
// Bridge.call("set_ai_status", ...). The sketch just stores and
// renders these numbers; see python/main.py / game/adaptive_ai.py.
struct AiStatus {
  uint8_t  learningPct;     // 0..100
  uint16_t samples;         // observation count
  char     favoriteWeapon;  // 'A'/'B'/'X'/'Y', or '-' if no data yet
  uint8_t  aggressionPct;   // 0..100
  uint8_t  fatigueEasePct;  // 0..100
  bool     valid;           // false until the first push arrives
};

AiStatus aiStatus = { 0, 0, '-', 0, 0, false };

// Wire-format copy of ControllerState returned by getControllerState().
// MSGPACK_DEFINE_MAP serializes the struct as a {"key": value} map so
// Python can read fields by name.
struct ControllerStateWire {
  MsgPack::str_t key_buttons       {"buttons"};       uint8_t buttons;
  MsgPack::str_t key_layerButtons  {"layerButtons"};   uint8_t layerButtons;
  MsgPack::str_t key_sleepWake     {"sleepWake"};      bool    sleepWake;
  MsgPack::str_t key_joyX          {"joyX"};           int16_t joyX;
  MsgPack::str_t key_joyY          {"joyY"};           int16_t joyY;
  MsgPack::str_t key_lightLevel    {"lightLevel"};     int16_t lightLevel;
  MsgPack::str_t key_micLevel      {"micLevel"};       int16_t micLevel;
  MsgPack::str_t key_accelX        {"accelX"};         int16_t accelX;
  MsgPack::str_t key_accelY        {"accelY"};         int16_t accelY;
  MsgPack::str_t key_accelZ        {"accelZ"};         int16_t accelZ;
  MsgPack::str_t key_mpuOk         {"mpuOk"};          bool    mpuOk;

  MSGPACK_DEFINE_MAP(
    key_buttons, buttons, key_layerButtons, layerButtons,
    key_sleepWake, sleepWake,
    key_joyX, joyX, key_joyY, joyY,
    key_lightLevel, lightLevel, key_micLevel, micLevel,
    key_accelX, accelX, key_accelY, accelY, key_accelZ, accelZ,
    key_mpuOk, mpuOk
  );
};

ControllerStateWire getControllerState() {
  ControllerStateWire w;
  w.buttons = state.buttons;
  w.layerButtons = state.layerButtons;
  w.sleepWake = state.sleepWake;
  w.joyX = state.joyX;
  w.joyY = state.joyY;
  w.lightLevel = state.lightLevel;
  w.micLevel = state.micLevel;
  w.accelX = state.accelX;
  w.accelY = state.accelY;
  w.accelZ = state.accelZ;
  w.mpuOk = state.mpuOk;
  return w;
}

// RPClite's incoming-argument deserializer only knows how to unpack
// primitives, strings, arrays, and maps -- NOT a bare custom struct,
// even one with MSGPACK_DEFINE_MAP (that macro only helps when the
// struct is *nested inside* another packed value, or when it's a
// return type, like ControllerStateWire above -- returning only needs
// packing). So incoming calls take plain positional parameters instead
// of a wrapper struct; the Python side calls with matching positional
// args (see push_ai_status()/HapticsBridge.tick() in python/main.py).

// favoriteWeapon arrives as a single-character MsgPack string
// ("A"/"B"/"X"/"Y"/"-"); we just take the first character. String
// uses .length(), not .size() (that's std::string, not arduino::String).
bool setAiStatus(uint8_t learningPct, uint16_t samples, MsgPack::str_t favoriteWeapon,
                  uint8_t aggressionPct, uint8_t fatigueEasePct) {
  aiStatus.learningPct = learningPct;
  aiStatus.samples = samples;
  aiStatus.favoriteWeapon = (favoriteWeapon.length() > 0) ? favoriteWeapon[0] : '-';
  aiStatus.aggressionPct = aggressionPct;
  aiStatus.fatigueEasePct = fatigueEasePct;
  aiStatus.valid = true;
  return true;
}

// motor is a single character: "L", "R", or "B" (both).
bool triggerVibration(MsgPack::str_t motorStr, uint16_t durationMs) {
  unsigned long nowMs = millis();
  char motor = (motorStr.length() > 0) ? motorStr[0] : 'B';
  if (motor == 'L' || motor == 'B') startVibe(vibL, nowMs, durationMs);
  if (motor == 'R' || motor == 'B') startVibe(vibR, nowMs, durationMs);
  return true;
}

// D12 double-tap toggle (see python/main.py's ControllerBridge.
// _toggle_oled_stats()): visible=false blanks the AI-status numbers
// on the OLED (aiRender() above) without touching anything else.
bool setOledVisibility(bool visible) {
  oledStatsHidden = !visible;
  lastOledMs = 0; // force an immediate redraw instead of waiting a frame
  return true;
}

// Averages a few readings at boot to find the joystick's actual rest
// position, since real modules commonly sit a little off from 512.
void calibrateJoystick() {
  const uint8_t SAMPLES = 8;
  long sumX = 0, sumY = 0;
  for (uint8_t i = 0; i < SAMPLES; i++) {
    sumX += analogRead(JOY_X_PIN);
    sumY += analogRead(JOY_Y_PIN);
    delay(2);
  }
  joyXCenter = (int16_t)(sumX / SAMPLES);
  joyYCenter = (int16_t)(sumY / SAMPLES);
}

// Buttons are INPUT_PULLUP, so pressed reads LOW. Returns an
// active-high bitmask (bit set = pressed).
uint8_t readButtons() {
  uint8_t b = 0;
  if (digitalRead(BTN1_PIN) == LOW) b |= (1 << 0);
  if (digitalRead(BTN2_PIN) == LOW) b |= (1 << 1);
  if (digitalRead(BTN3_PIN) == LOW) b |= (1 << 2);
  if (digitalRead(BTN4_PIN) == LOW) b |= (1 << 3);
  return b;
}

uint8_t readLayerButtons() {
  uint8_t b = 0;
  if (digitalRead(LAYER1_BTN_PIN) == LOW) b |= (1 << 0);
  if (digitalRead(LAYER2_BTN_PIN) == LOW) b |= (1 << 1);
  if (digitalRead(LAYER3_BTN_PIN) == LOW) b |= (1 << 2);
  return b;
}

bool mpuInit() {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_PWR_MGMT_1);
  Wire.write(0);
  return (Wire.endTransmission() == 0);
}

bool mpuRead(int16_t &ax, int16_t &ay, int16_t &az) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;

  Wire.requestFrom((int)MPU6050_ADDR, 6);
  if (Wire.available() < 6) return false;

  ax = (Wire.read() << 8) | Wire.read();
  ay = (Wire.read() << 8) | Wire.read();
  az = (Wire.read() << 8) | Wire.read();
  return true;
}

// ---- OLED: AI learning status screen ----

void drawBar(int16_t x, int16_t y, int16_t w, int16_t h, uint8_t pct) {
  oled.drawFrame(x, y, w, h);
  int16_t fillW = (int16_t)((long)w * pct / 100);
  if (fillW > 0) oled.drawBox(x, y, fillW, h);
}

void instructionsRender() {
  oled.clearBuffer();

  oled.setFont(u8g2_font_6x10_tf);
  oled.setCursor(0, 9);
  oled.print(INSTRUCTION_PAGES[instructionPage][0]);

  oled.setFont(u8g2_font_5x7_tf);
  oled.setCursor(0, 24);
  oled.print(INSTRUCTION_PAGES[instructionPage][1]);
  oled.setCursor(0, 36);
  oled.print(INSTRUCTION_PAGES[instructionPage][2]);
  oled.setCursor(0, 48);
  oled.print(INSTRUCTION_PAGES[instructionPage][3]);

  char footer[24];
  snprintf(footer, sizeof(footer), "%u/%u  D9>D10<  D8 OK",
           instructionPage + 1, INSTRUCTION_PAGE_COUNT);
  oled.setCursor(0, 62);
  oled.print(footer);

  oled.sendBuffer();
}

// Reads D8/D9/D10 directly (not via readLayerButtons()) and turns
// clean rising edges into page-forward / page-back / confirm actions.
// Only called while oledScreen == SCREEN_INSTRUCTIONS.
void handleInstructionButtons(unsigned long nowMs) {
  bool d8Pressed  = (digitalRead(LAYER1_BTN_PIN) == LOW);
  bool d9Pressed  = (digitalRead(LAYER2_BTN_PIN) == LOW);
  bool d10Pressed = (digitalRead(LAYER3_BTN_PIN) == LOW);

  bool d8Edge  = d8Pressed  && !prevD8Pressed;
  bool d9Edge  = d9Pressed  && !prevD9Pressed;
  bool d10Edge = d10Pressed && !prevD10Pressed;

  prevD8Pressed = d8Pressed;
  prevD9Pressed = d9Pressed;
  prevD10Pressed = d10Pressed;

  if (nowMs - lastInstructionActionMs < INSTRUCTION_DEBOUNCE_MS) return;

  if (d9Edge && instructionPage < INSTRUCTION_PAGE_COUNT - 1) {
    instructionPage++;
    lastInstructionActionMs = nowMs;
    lastOledMs = 0; // redraw now instead of waiting for the next tick
  } else if (d10Edge && instructionPage > 0) {
    instructionPage--;
    lastInstructionActionMs = nowMs;
    lastOledMs = 0;
  } else if (d8Edge) {
    oledScreen = SCREEN_AI_STATUS; // confirm -- dismiss for the session
    lastInstructionActionMs = nowMs;
    lastOledMs = 0;
  }
}

void aiRender() {
  oled.clearBuffer();

  oled.setFont(u8g2_font_6x10_tf);
  oled.setCursor(0, 9);
  oled.print("AI LEARNING");

  if (oledStatsHidden) {
    oled.setFont(u8g2_font_5x7_tf);
    oled.setCursor(0, 24);
    oled.print("stats hidden");
    oled.setCursor(0, 36);
    oled.print("(double-tap D12");
    oled.setCursor(0, 46);
    oled.print(" to show again)");
    oled.sendBuffer();
    return;
  }

  if (!aiStatus.valid) {
    oled.setFont(u8g2_font_5x7_tf);
    oled.setCursor(0, 24);
    oled.print("waiting for data...");
    oled.sendBuffer();
    return;
  }

  oled.setFont(u8g2_font_5x7_tf);
  oled.setCursor(0, 21);
  oled.print("Learning");
  drawBar(0, 24, 100, 8, aiStatus.learningPct);
  oled.setCursor(104, 31);
  oled.print(aiStatus.learningPct);

  oled.setCursor(0, 41);
  oled.print("Aggression");
  drawBar(0, 44, 100, 8, aiStatus.aggressionPct);
  oled.setCursor(104, 51);
  oled.print(aiStatus.aggressionPct);

  char line[24];
  snprintf(line, sizeof(line), "n=%u  wpn:%c  ease:%u%%",
           aiStatus.samples, aiStatus.favoriteWeapon, aiStatus.fatigueEasePct);
  oled.setCursor(0, 62);
  oled.print(line);

  oled.sendBuffer();
}

void setup() {
  Wire.begin();

  pinMode(VIB_LEFT_PIN, OUTPUT);
  pinMode(VIB_RIGHT_PIN, OUTPUT);
  digitalWrite(VIB_LEFT_PIN, LOW);
  digitalWrite(VIB_RIGHT_PIN, LOW);

  pinMode(BTN1_PIN, INPUT_PULLUP);
  pinMode(BTN2_PIN, INPUT_PULLUP);
  pinMode(BTN3_PIN, INPUT_PULLUP);
  pinMode(BTN4_PIN, INPUT_PULLUP);

  pinMode(LAYER1_BTN_PIN, INPUT_PULLUP);
  pinMode(LAYER2_BTN_PIN, INPUT_PULLUP);
  pinMode(LAYER3_BTN_PIN, INPUT_PULLUP);

  pinMode(SLEEP_WAKE_PIN, INPUT_PULLUP);

  // A0-A2 need no pinMode() for analogRead().

  state.mpuOk = mpuInit();
  calibrateJoystick();

  oled.setI2CAddress(OLED_ADDR << 1); // u8g2 wants the 8-bit address
  oledOk = oled.begin();
  if (!oledOk) {
    Monitor.begin(115200);
    Monitor.println(F("OLED init failed -- check wiring/address (0x3C)."));
  }

  Bridge.begin();
  Bridge.provide("get_controller_state", getControllerState);
  Bridge.provide("set_ai_status", setAiStatus);
  Bridge.provide("trigger_vibration", triggerVibration);
  Bridge.provide("set_oled_visibility", setOledVisibility);
}

void loop() {
  unsigned long nowMs = millis();

  state.buttons = readButtons();
  state.layerButtons = readLayerButtons();
  state.sleepWake = (digitalRead(SLEEP_WAKE_PIN) == LOW);

  if (oledScreen == SCREEN_INSTRUCTIONS) {
    handleInstructionButtons(nowMs);
    // Harmless now that nothing on the Python side reads layerButtons
    // for a layer jump anymore, but zeroed anyway while this screen
    // owns D8/D9/D10, just in case.
    state.layerButtons = 0;
  }
  int16_t rawJoyX = analogRead(JOY_X_PIN) - joyXCenter;
  int16_t rawJoyY = analogRead(JOY_Y_PIN) - joyYCenter;
  applyJoystickRotation(rawJoyX, rawJoyY, state.joyX, state.joyY);
  state.lightLevel = analogRead(PHOTO_PIN);
  state.micLevel = analogRead(MIC_PIN);

  int16_t ax, ay, az;
  if (mpuRead(ax, ay, az)) {
    state.accelX = ax;
    state.accelY = ay;
    state.accelZ = az;
    state.mpuOk = true;
  } else {
    state.mpuOk = false;
  }

  vibeUpdate(vibL, nowMs);
  vibeUpdate(vibR, nowMs);

  if (oledOk && nowMs - lastOledMs >= OLED_FRAME_MS) {
    if (oledScreen == SCREEN_INSTRUCTIONS) {
      instructionsRender();
    } else {
      aiRender();
    }
    lastOledMs = nowMs;
  }

  delay(8);
}
