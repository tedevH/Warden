/*
  Warden Box: a safety button, a spending-limit knob and a status light for Warden.

  Talks to hardware/bridge.py on the Mac over USB serial at 9600 baud.
    Arduino -> Mac:  PRESS            the button was pressed
                     KNOB <0..1023>   the knob moved
    Mac -> Arduino:  L0  all good            light off
                     L1  approval needed     slow blink, one beep
                     L2  locked down         solid on, long beep
                     L3  scam blocked        fast blink, three beeps

  Default pins match the Seeed Grove Beginner Kit (everything is already wired on that board).
  On a plain Uno + breadboard, wire your parts to these pins or change the numbers below.
  The Uno's built-in LED (pin 13) always mirrors the light, so it works with no LED at all.
*/
const int BUTTON_PIN = 6;         // Grove button: D6
const bool BUTTON_ACTIVE_HIGH = true;  // Grove button = true. Bare button from pin to GND = false.
const int KNOB_PIN = A0;          // rotary angle sensor: A0
const int LED_PIN = 4;            // LED: D4
const int BUZZER_PIN = 5;         // buzzer: D5 (leave unconnected if you have none)

char mode = '0';
bool wasDown = false;
unsigned long downAt = 0, lastKnobAt = 0;
int lastKnob = -100;

void beep(int times, int ms) {
  for (int i = 0; i < times; i++) {
    tone(BUZZER_PIN, 1800, ms);
    delay(ms + 80);
  }
}

void setLight(bool on) {
  digitalWrite(LED_PIN, on ? HIGH : LOW);
  digitalWrite(LED_BUILTIN, on ? HIGH : LOW);
}

void setup() {
  Serial.begin(9600);
  pinMode(BUTTON_PIN, BUTTON_ACTIVE_HIGH ? INPUT : INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  Serial.println("READY");
}

void loop() {
  // --- commands from the Mac ---
  while (Serial.available() >= 2) {
    if (Serial.read() != 'L') continue;
    char m = Serial.read();
    if (m < '0' || m > '3' || m == mode) continue;
    mode = m;
    if (mode == '1') beep(1, 120);
    if (mode == '2') beep(1, 600);
    if (mode == '3') beep(3, 120);
  }

  // --- light ---
  unsigned long now = millis();
  if (mode == '0') setLight(false);
  else if (mode == '2') setLight(true);
  else setLight((now / (mode == '1' ? 500 : 120)) % 2 == 0);

  // --- button (debounced: must be held 40 ms) ---
  bool down = digitalRead(BUTTON_PIN) == (BUTTON_ACTIVE_HIGH ? HIGH : LOW);
  if (down && !wasDown) downAt = now;
  if (!down && wasDown && now - downAt > 40) Serial.println("PRESS");
  wasDown = down;

  // --- knob (report when it moves, at most 5 times a second) ---
  int knob = analogRead(KNOB_PIN);
  if (abs(knob - lastKnob) > 12 && now - lastKnobAt > 200) {
    lastKnob = knob;
    lastKnobAt = now;
    Serial.print("KNOB ");
    Serial.println(knob);
  }
  delay(5);
}
