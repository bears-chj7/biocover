# 배선 및 연결 상태

2026-09-13 사용자 정정 반영. P 번호는 40핀 헤더의 **물리 핀 번호**입니다.
배선은 사용자 제공 정보이며 전압·저항을 계측기로 확인한 것은 아닙니다.

| 장치 | 신호 연결 | 전원 | 현재 상태 |
|---|---|---|---|
| MCP3008 | DIN P19, DOUT P21, CLK P23, CS P24 | VDD/VREF P1 3.3V | 연결, ADC 값 읽힘 |
| MQ-4 #1 유입 | AOUT CH0 | P2 5V | 연결 |
| MQ-4 #2 유출 | AOUT CH1 | P2 5V | 연결 |
| MQ-4 #3 | AOUT CH2 예정 | 5V 예정 | **미연결** |
| MQ-4 #4 | AOUT CH3 예정 | 5V 예정 | **미연결** |
| 정전용량식 토양수분 | AOUT CH4 | P1 3.3V | 연결 |
| DHT22/AM2302 | DATA P15, 10kΩ 풀업 → 3.3V | P17 3.3V | 연결, P15 수정 후 펄스 검출·유효 프레임 미확보 |
| DS18B20 | DATA P7, 4.7kΩ 풀업 → 3.3V | P1 3.3V | 연결, 외부 드라이버 설치·정상 ID 미검출 |
| CM1106 | TX P10 / RX P8 예정 | P2 5V 예정 | **미연결** |

전 장치 공통 GND. MCP3008 AGND·DGND도 GND에 연결합니다. CH5~CH7은 미사용입니다.
토양수분은 CH2에서 CH4로 변경되었습니다. DHT22의 현재 DATA 연결은 P11이 아닌 P15입니다.

Jetson-IO의 spi1 (P19·21·23·24·26)은 이 장치에서 `/dev/spidev0.0`의 CS0 경로에 대응합니다.
P15는 gpiochip0 line 85 (PN.01), P7은 line 144 (PAC.06)입니다.
이는 현재 보드의 로컬 NVIDIA 핀 매핑 기준이며 다른 보드에 그대로 적용하지 않습니다.

MCP3008 VREF/VDD가 3.3V이므로 ADC 입력 범위를 0~3.3V로 제한해야 합니다.
MQ-4 AOUT의 분압 유무 및 실제 최대 전압은 아직 확인되지 않았습니다.
참고: [Microchip MCP3008 데이터시트](https://ww1.microchip.com/downloads/aemDocuments/documents/MSLD/ProductDocuments/DataSheets/MCP3004-MCP3008-Data-Sheet-DS20001295.pdf).

## 사용자 추가 확인

2026-09-13: DS18B20 DATA 풀업 저항이 실제로 미연결이라고 확인됨. DATA(P7)–3.3V(P1)에 4.7kΩ 저항 추가 안내, 연결 완료는 아직 미확인.
DHT22는 사용자 Arduino 환경에서 정상 읽기 보고. Jetson 측 유효 프레임 확보는 계속 미완료.
