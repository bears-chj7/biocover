# UNO 모터 제어와 센서 혼합 시리얼

2026-10-09 사용자 제공 스케치 기준: DS18B20 D2, DHT22 D3, SG90 D9.
USB는 9600bps, 8N1이며 같은 연결에서 온도·습도 수신과 모터 명령 송수신을 처리한다.
MQ-4 #1은 유입, #2·#3·#4는 유출이다.

## 웹 사용

1. 코드 갱신 후 `sudo systemctl restart biocover-web.service`를 실행하고 페이지를 새로고침한다.
2. 실시간 탭의 **모터 · SG90**에서 **아두이노 연결**을 누른다.
   측정 중이라면 이미 연결되어 있다. 연결만으로 CSV 기록을 시작하지 않는다.
3. **상태 확인**으로 UNO 설정 각도를 읽는다. 아직 첫 명령을 받지 않았다면 **설정 안 됨**이다.
4. **목표 각도**에 0~180 정수를 입력하고 **각도 전송**을 누른다.
   입력값을 바꾸기만 해서는 전송하지 않는다. `#ANGLE` 응답이 와야 확인 완료로 표시한다.

표시값은 UNO가 설정했다고 응답한 각도이며 실제 모터 위치를 측정한 값이 아니다.
USB를 열면 UNO가 재시작될 수 있다. 재시작·연결 해제 시 확인 각도를 비우며 이전 각도를 자동 전송하지 않는다.
측정 정지 시 USB 연결도 닫히므로 이후 제어하려면 다시 **아두이노 연결**을 누른다.
재생 탭에는 저장된 각도만 표시하며 실제 모터 제어 기능은 없다.

## 프로토콜

| 방향 | 줄 형식 | 처리 |
|---|---|---|
| Jetson → UNO | `30\n` | 30도 설정. 숫자와 줄바꿈만 전송 |
| Jetson → UNO | `STATUS\n` | 설정 각도 조회. 각도 명령이 아님 |
| UNO → Jetson | `#READY` | 재시작. 이전 센서 캐시·각도·대기 명령 초기화 |
| UNO → Jetson | `#ANGLE,30` | 각도 명령 확인 응답 |
| UNO → Jetson | `#STATUS,ANGLE,30` | 마지막으로 설정한 각도 |
| UNO → Jetson | `#STATUS,ANGLE,NONE` | 재시작 이후 각도 미설정 |
| UNO → Jetson | `#ERR,INVALID_ANGLE` / `#ERR,COMMAND_TOO_LONG` | 명령 오류 표시 |
| UNO → Jetson | `time_ms,DS18B20_C,DHT22_C,humidity_pct` | 센서 CSV 헤더 |
| UNO → Jetson | `2750,27.94,27.90,45.10` | 기존과 같은 센서값 |

첫 센서 행 수신 후 자동으로 `STATUS` 한 번을 조회한다. 각도 명령은 자동 전송하지 않는다.
한 번에 한 명령만 처리하고, 기본 3초 이내 확인 응답이 없으면 오류로 표시한다.
시간 초과나 재연결 후에는 숫자 명령을 재전송하지 않으므로 상태를 조회한 뒤 사용자가 판단한다.
기존 CLI 수신기도 `#` 메시지를 표준 오류에 출력하고 센서 CSV/JSON 행에 섞지 않는다.

## API 및 CSV

- `GET /api/motor`: 현재 연결·마지막 확인 각도·명령 대기·오류 상태. 시리얼 전송 없음.
- `POST /api/motor/connect`, JSON `{}`: USB 연결. 측정/CSV를 시작하지 않는다.
- `POST /api/motor/status`, JSON `{}`: `STATUS` 조회 후 응답 반환.
- `POST /api/motor`, JSON `{"angle":30}`: 숫자 명령 전송. 정수 범위·동시 명령·기존 Origin 검증 적용.
- 새 5초 측정 CSV에는 `motor_angle`, `motor_reported_at`, `motor_status`가 추가된다.
  각도는 마지막 확인값이며 `motor_status`는 `known`, `unset`, `unknown`, `pending`, `error`, `disconnected` 중 하나다.
  과거 CSV에 모터 기록이 없으면 각도는 빈 값/기록 없음으로 취급한다. 0도로 보완하지 않는다.

사용자가 제공한 스케치를 `hardware/arduino/biocover_sensors/biocover_sensors.ino`에 저장했다.
이 작업에서 UNO에 펌웨어를 업로드하지 않았다. 로컬에 arduino-cli가 없어 스케치 재컴파일은 하지 않았다.
