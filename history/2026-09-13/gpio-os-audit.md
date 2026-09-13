# GPIO OS 점검 (사용자 실행 결과)

- 커널 5.15.148-tegra. DEFAULT JetsonIO, OVERLAYS /boot/ds18b20-pin7.dtbo.
- wire / w1_gpio 로드됨. w1_therm 설치됨, 로드 목록에는 없음.
  세 모듈 vermagic은 실행 커널과 일치. 이것만으로 타이밍 정상까지 증명하지는 않음.
- P7: PAC.06, gpiochip0 line 144, onewire 점유, output/open-drain 표시.
  live DT gpios = <0xf3 0xa6 0>, status=okay.
  pinconf: pull=0, tristate=0, enable-input=1, open-drain=0,
  gpio-mode=0, function=rsvd2.
- P15: PN.01, line 85, unused/input. pinconf: pull=0, tristate=0,
  enable-input=1, open-drain=1, io-reset=1, rcv-sel=1, io-hv=1,
  gpio-mode=1, function=rsvd1. 이번 감사는 GPIO를 요청하지 않았으므로
  측정 프로그램이 핀을 점유한 동안의 설정과 구분해야 함.
- w1_bus_master1만 존재. attempts=40, search=-1, slave_count=0,
  slaves=not found. 실제 센서 ROM/CRC/온도 미확인.
- 로그: gpio-492 (onewire): enforced open drain please flag it properly
  in DT/ACPI DSDT/board file (14.591649, 873.468775초).
  로컬 w1-gpio 소스는 기본 GPIOD_OUT_LOW_OPEN_DRAIN을 요청함.
  이 경고는 DT 플래그와 드라이버 요청의 차이이며, 단독으로 실패 증거는 아님.
  gpiolib의 소프트웨어 오픈드레인과 핀mux의 open-drain 비트는 구분할 것.

다음 단계: w1_therm 실제 로딩 성공 여부 확인. 이 모듈의 미로드만으로
센서 ROM 검색 실패를 설명할 수 없으므로, 해결됐다고 판단하지 않을 것.
SPI 및 부팅 설정은 변경하지 않음.

참고 소스: https://raw.githubusercontent.com/torvalds/linux/v5.15/drivers/gpio/gpiolib.c

## 추가 실측

- 사용자가 modprobe -v w1_therm 실행: insmod 경로 출력, 오류 보고 없음.
- 이후 read_temperature.py: DS18B20 not detected. 모듈 로딩으로 검색 실패가
  해결되지 않음.
- check_p7_voltage.py의 RELEASED → LOW → RELEASED 구간에서 사용자가
  보고한 전압은 3.4 → 1.6 → 3.4 V. 전체 실행 로그는 아직 받지 않음.
- LOW 유지 중 측정값이라면 DS18B20 VIL 최대 0.8 V를 만족하지 못함.
  내부 GPIO readback과 실제 패드 전압을 구분해야 함. 핀 설정/구동 경로와
  외부 부하를 아직 구분하지 못했으므로 센서 또는 보드 고장으로 단정하지 않음.
- 다음 비교: 전원 차단 후 센서 DATA만 분리하고 P7–4.7kΩ–3.3V는 유지,
  같은 정적 전압 검사를 반복. SPI/부팅 설정 변경 없음.

전압 규격: https://www.analog.com/media/en/technical-documentation/data-sheets/ds18b20.pdf

## 원인 후보를 뒷받침하는 캐리어 보드 회로 확인

사용자가 비교 검사 출력과 동일 전압 3.4 → 1.6 → 3.4 V를 보고함.
GPIO read는 1 → 0 → 0. 마지막 출력은 입력 요청 직후 한 번 읽은 값이므로
수 초 뒤 멀티미터 측정과 동시 샘플이 아님. 복원 완료 출력은 제공되지 않음.
앞선 안내는 센서 DATA 분리 검사였지만, 사용자가 분리 여부를 별도로 명시하지는 않음.

NVIDIA Orin Nano 개발 키트 캐리어 보드 사양 v1.3 표 3-3에서
P7/PAC.06과 P15/PN.01 모두 주석 3(TXB0108 전압 변환기 경유)에 해당.
TI TXB0108 데이터시트는 외부 풀업/풀다운을 50kΩ보다 크게 요구하며,
오픈드레인 양방향 1-Wire 용도로 사용하지 말라고 명시함.
TI 근사식 VOL = VCC × 4.5k / (Rpullup + 4.5k)에
VCC=3.4 V, Rpullup=4.7kΩ를 넣으면 약 1.66 V로 실측과 부합함.
이는 DS18 통신 실패의 강한 원인 근거. 기존 일반적인 P7+4.7kΩ 직결 안내는
이 캐리어 보드에 적합하지 않았음. DHT22의 내부 풀업도 같은 회로 제한의
영향을 받을 수 있지만, DHT 실패 전체 원인이 확정된 것은 아님.

OS 재설치/핀mux 반복 변경 또는 단순 50kΩ 이상 저항 교체를
검증된 해결책으로 제시하지 않음. 센서 통신을 Arduino에서 처리하고 USB로
Jetson에 전달하거나, 적합한 1-Wire 브리지 등 연결 구조 변경을 검토할 것.

- NVIDIA: https://developer.nvidia.com/downloads/assets/embedded/secure/jetson/orin_nano/docs/jetson_orin_nano_devkit_carrier_board_specification_sp.pdf
- TI (7.3.5 및 8.2.2): https://www.ti.com/lit/ds/symlink/txb0108.pdf
