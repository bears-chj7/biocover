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
