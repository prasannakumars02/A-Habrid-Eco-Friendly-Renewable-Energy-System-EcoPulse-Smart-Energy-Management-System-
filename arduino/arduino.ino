#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "DHT.h"

// === LCD Setup ===
LiquidCrystal_I2C lcd(0x27, 16, 2);  // Use 0x3F if 0x27 doesn't work

// === DHT Sensor ===
#define DHTPIN 2
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// === Voltage and Current Sensors ===
#define SOLAR_V A0
#define SOLAR_I A1
#define WIND_V  A2
#define WIND_I  A3
#define OTHER_V A6
#define OTHER_I A7

// === Relay ===
#define RELAY_PIN 7

// === Calibration Constants ===
const float VREF = 5.0;            // Reference voltage for ADC
const float ADC_RES = 1023.0;      // 10-bit ADC
const float VOLT_DIV = 11.0;       // Voltage divider ratio
const float ZERO_CURRENT_V = 2.5;  // ACS712 zero current voltage
const float SENSITIVITY = 0.100;   // 100mV/A for ACS712-20A

void setup() {
  lcd.init();
  lcd.backlight();
  Serial.begin(9600);
  dht.begin();

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  // ====== ADDED: Project Title Screen ======
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(" HYBRID RENEWABLE");
  lcd.setCursor(0, 1);
  lcd.print("  ENERGY SYSTEM ");
  delay(1000); // Show title for 3 seconds
  // ========================================

  delay(2000);  // Allow DHT to stabilize
}

void loop() {
  // === Solar Source ===
  float sV = (analogRead(SOLAR_V) * VREF / ADC_RES) * VOLT_DIV;
  float sI = ((analogRead(SOLAR_I) * VREF / ADC_RES) - ZERO_CURRENT_V) / SENSITIVITY;
  if (abs(sI) < 0.05) sI = 0;
  float sP = sV * sI;

  // === Wind Source ===
  float wV = (analogRead(WIND_V) * VREF / ADC_RES) * VOLT_DIV;
  float wI = ((analogRead(WIND_I) * VREF / ADC_RES) - ZERO_CURRENT_V) / SENSITIVITY;
  if (abs(wI) < 0.05) wI = 0;
  float wP = wV * wI;

  // === Other Source ===
  float oV = (analogRead(OTHER_V) * VREF / ADC_RES) * VOLT_DIV;
  float oI = ((analogRead(OTHER_I) * VREF / ADC_RES) - ZERO_CURRENT_V) / SENSITIVITY;
  if (abs(oI) < 0.05) oI = 0;
  float oP = oV * oI;

  // === Temperature & Humidity ===
  float hum = dht.readHumidity();
  float temp = dht.readTemperature();

  // === Total Power ===
  float totalP = sP + wP + oP;

  // === Relay Control ===
  if (totalP > 10) digitalWrite(RELAY_PIN, HIGH);
  else digitalWrite(RELAY_PIN, LOW);

  // === LCD Display (Updated format) ===

  // --- Solar ---
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("S.V="); lcd.print(sV,1);
  lcd.print(" S.C="); lcd.print(sI,1);
  lcd.setCursor(0,1);
  lcd.print("S.P="); lcd.print(sP,1);
  delay(2000);

  // --- Wind ---
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("W.V="); lcd.print(wV,1);
  lcd.print(" W.C="); lcd.print(wI,1);
  lcd.setCursor(0,1);
  lcd.print("W.P="); lcd.print(wP,1);
  delay(2000);

  // --- Other Source ---
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("O.V="); lcd.print(oV,1);
  lcd.print(" O.C="); lcd.print(oI,1);
  lcd.setCursor(0,1);
  lcd.print("O.P="); lcd.print(oP,1);
  delay(2000);

  // --- Environment ---
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Temp="); lcd.print(temp,1); lcd.print("C");
  lcd.setCursor(0,1);
  lcd.print("Hum="); lcd.print(hum,1); lcd.print("%");
  delay(2000);

  // === Serial Output (Formatted) ===
  Serial.println("----------------------------------");
  Serial.print("S.V="); Serial.print(sV,1);
  Serial.print("  S.C="); Serial.print(sI,1);
  Serial.print("  S.P="); Serial.println(sP,1);

  Serial.print("W.V="); Serial.print(wV,1);
  Serial.print("  W.C="); Serial.print(wI,1);
  Serial.print("  W.P="); Serial.println(wP,1);

  Serial.print("O.V="); Serial.print(oV,1);
  Serial.print("  O.C="); Serial.print(oI,1);
  Serial.print("  O.P="); Serial.println(oP,1);

  Serial.print("Temp="); Serial.print(temp,1);
  Serial.print("°C  Hum="); Serial.print(hum,1);
  Serial.println("%");

  Serial.print("Total Power="); Serial.print(totalP,1);
  Serial.println(" W");
  Serial.println("----------------------------------");

  delay(1000);
}
