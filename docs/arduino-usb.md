# UNO USB 온도·습도 수신

사용자가 UNO에서 센서 동작을 확인하고 제공한 스케치는
[biocover_sensors.ino](../hardware/arduino/biocover_sensors/biocover_sensors.ino)에
저장했다. 실제 스케치 기준 **DS18 D2, DHT22 D3**이며, 과거 제안의 핀 배치와 다르다.
이 작업에서 펌웨어를 다시 업로드하지 않았다.

- UART 출력 9600bps, 8N1, 약 2초 주기.
- 헤더: `time_ms,DS18B20_C,DHT22_C,humidity_pct`.
- `time_ms`는 UNO 루프 시작 시점의 부팅 후 밀리초다. 실제 측정 완료 시각이나
  UTC가 아니며, UNO 리셋 및 millis 래핑 시 감소할 수 있다.
- Jetson 수신기는 `received_at_utc`를 별도로 저장한다.
- NaN/무한대/범위 밖 값은 JSON null, CSV 빈칸과 invalid_fields로 보존한다.
  범위 내 값도 교정 또는 정확도를 검증한 것은 아니다.
- USB 포트를 열면 UNO가 리셋될 수 있다. 시작 헤더와 잘린 행을 처리한다.
- 시리얼 모니터 등 다른 읽기 프로그램은 닫고 실행한다.

## 2026-09-13 Jetson 점검

USB 장치 `1a86:7523` CH340 인식, 인터페이스 Driver는 비어 있음.
`CONFIG_USB_SERIAL_CH341` 미설정, ch341 모듈 없음, ttyUSB/ttyACM 포트 없음.
기존 usbserial.ko는 설치되어 있다. Linux stable v5.15.148의 CH341 소스를
현재 NVIDIA 헤더와 Module.symvers로 외부 모듈 빌드했다.
빌드 성공, vermagic 일치. 컴파일러 패키지 리비전 차이 경고는 있었지만 둘 다 GCC 11.4.0.
실제 로딩과 센서 수신은 사용자 sudo 실행 후 검증해야 한다.

빌드 재현 (저장소 루트):

```bash
mkdir -p build/ch341
curl -fL https://raw.githubusercontent.com/gregkh/linux/v5.15.148/drivers/usb/serial/ch341.c -o build/ch341/ch341.c
printf 'obj-m += ch341.o\n' > build/ch341/Makefile
make -C /lib/modules/5.15.148-tegra/build M="$PWD/build/ch341" modules
```

임시 드라이버 로드 및 5개 행 수신:

```bash
sudo python3 scripts/read_arduino_usb.py --load-driver --samples 5
```

이 옵션은 usbserial과 빌드된 ch341을 현재 부팅에 로드한다. 모듈은 이후 읽기에
필요하므로 종료 후에도 유지한다. /boot와 영구 모듈 설치 경로는 변경하지 않으며
재부팅하면 다시 로드해야 한다. 커널 버전/모듈 vermagic이 달라지면 중단한다.

로드 이후 연속 CSV 수집 (파일은 새로 생성하며 기존 파일 덮어쓰기 거부):

```bash
sudo python3 scripts/read_arduino_usb.py --samples 0 --csv /tmp/biocover-uno.csv
```

여러 USB 시리얼 포트가 있으면 `--port /dev/serial/by-id/해당장치`로 지정한다.
일반 사용자 권한 설정과 영구 드라이버 설치는 수신 성공 확인 이후 진행할 수 있다.

가상 터미널 검증 통과: CSV 헤더, 분할 수신, 잘못된 행, NaN/범위 검사,
CSV 저장, 타임아웃, 종료 후 포트 재사용. UNO 실측 검증과는 구분한다.
