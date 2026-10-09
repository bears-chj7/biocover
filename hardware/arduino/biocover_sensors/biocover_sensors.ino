#include <OneWire.h>
#include <DallasTemperature.h>
#include <DHT.h>
#include <Servo.h>
#include <stdlib.h>
#include <math.h>

// 사용자 제공 2026-10-09 펌웨어: 센서 D2/D3, SG90 D9.
#define DS18B20_PIN 2
#define DHT22_PIN 3
#define SG90_PIN 9
#define DHTTYPE DHT22

OneWire oneWire(DS18B20_PIN);
DallasTemperature ds18b20(&oneWire);
DHT dht(DHT22_PIN, DHTTYPE);
Servo motor;
int currentAngle = -1;
char commandBuffer[24];
uint8_t commandIndex = 0;
const unsigned long SENSOR_INTERVAL = 2000;
unsigned long lastSensorTime = 0;
unsigned long conversionStart = 0;
bool conversionPending = false;

void setup() {
  Serial.begin(9600);
  ds18b20.begin();
  ds18b20.setResolution(12);
  ds18b20.setWaitForConversion(false);
  dht.begin();
  // 첫 각도 명령 전에는 attach하지 않는다.
  Serial.println("#READY");
  Serial.println("time_ms,DS18B20_C,DHT22_C,humidity_pct");
}

void processCommand(char* command) {
  while (*command == ' ' || *command == '\t') command++;
  int length = strlen(command);
  while (length > 0 && (command[length-1] == ' ' || command[length-1] == '\t')) {
    command[--length] = '\0';
  }
  if (strcmp(command, "STATUS") == 0) {
    Serial.print("#STATUS,ANGLE,");
    if (currentAngle < 0) Serial.println("NONE");
    else Serial.println(currentAngle);
    return;
  }
  if (length == 0) return;
  char* endPtr;
  long angle = strtol(command, &endPtr, 10);
  if (*endPtr != '\0' || endPtr == command || angle < 0 || angle > 180) {
    Serial.println("#ERR,INVALID_ANGLE");
    return;
  }
  if (!motor.attached()) motor.attach(SG90_PIN);
  motor.write((int)angle);
  currentAngle = (int)angle;
  Serial.print("#ANGLE,");
  Serial.println(currentAngle);
}

void readSerialCommand() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (commandIndex > 0) {
        commandBuffer[commandIndex] = '\0';
        processCommand(commandBuffer);
        commandIndex = 0;
      }
    } else if (commandIndex < sizeof(commandBuffer) - 1) {
      commandBuffer[commandIndex++] = c;
    } else {
      commandIndex = 0;
      Serial.println("#ERR,COMMAND_TOO_LONG");
    }
  }
}

void printSensorData(unsigned long timestamp) {
  float dsTemp = ds18b20.getTempCByIndex(0);
  float dhtTemp = dht.readTemperature();
  float humidity = dht.readHumidity();
  Serial.print(timestamp);
  Serial.print(",");
  if (dsTemp == DEVICE_DISCONNECTED_C || dsTemp < -55.0 || dsTemp > 125.0) {
    Serial.print("NaN");
  } else Serial.print(dsTemp, 2);
  Serial.print(",");
  if (isnan(dhtTemp)) Serial.print("NaN");
  else Serial.print(dhtTemp, 2);
  Serial.print(",");
  if (isnan(humidity)) Serial.println("NaN");
  else Serial.println(humidity, 2);
}

void loop() {
  readSerialCommand();
  unsigned long now = millis();
  if (!conversionPending && now - lastSensorTime >= SENSOR_INTERVAL) {
    lastSensorTime = now;
    ds18b20.requestTemperatures();
    conversionStart = now;
    conversionPending = true;
  }
  if (conversionPending && now - conversionStart >= 750) {
    conversionPending = false;
    printSensorData(now);
  }
}
