#include <OneWire.h>
#include <DallasTemperature.h>
#include <DHT.h>

const uint8_t DS18B20_PIN = 2;
const uint8_t DHT22_PIN = 3;
const unsigned long MEASUREMENT_INTERVAL_MS = 2000;

OneWire oneWire(DS18B20_PIN);
DallasTemperature ds18b20(&oneWire);
DHT dht(DHT22_PIN, DHT22);

unsigned long lastMeasurementMs = 0;

void setup() {
  Serial.begin(9600);
  ds18b20.begin();
  ds18b20.setResolution(12);
  ds18b20.setWaitForConversion(true);
  dht.begin();
  Serial.println(F("time_ms,DS18B20_C,DHT22_C,humidity_pct"));
}

void loop() {
  unsigned long now = millis();
  if (now - lastMeasurementMs < MEASUREMENT_INTERVAL_MS) {
    return;
  }
  lastMeasurementMs = now;
  float humidity = dht.readHumidity();
  float dhtTemperature = dht.readTemperature();
  ds18b20.requestTemperatures();
  float dsTemperature = ds18b20.getTempCByIndex(0);
  Serial.print(now);
  Serial.print(',');
  if (isnan(dsTemperature) || dsTemperature < -55.0f || dsTemperature > 125.0f) {
    Serial.print(F("NaN"));
  } else {
    Serial.print(dsTemperature, 2);
  }
  Serial.print(',');
  if (isnan(dhtTemperature)) {
    Serial.print(F("NaN"));
  } else {
    Serial.print(dhtTemperature, 2);
  }
  Serial.print(',');
  if (isnan(humidity)) {
    Serial.println(F("NaN"));
  } else {
    Serial.println(humidity, 2);
  }
}
