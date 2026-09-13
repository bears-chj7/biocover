# UNO USB 온도·습도 수신

**최신 결과:** 2026-09-13 21:19 KST 사용자 실행에서 Jetson USB 수신 성공.
5개 행 중 4개는 세 항목 모두 유효했고 첫 행의 DS18만 결측이었다.
아래의 미검증 표기는 각 단계 당시 기록이다.

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

## 최초 실제 로딩 결과: brltty 충돌

사용자 실행에서 CH341 로딩 성공, ttyUSB0 생성 및 CSV 헤더 일부 수신 후
EIO로 종료됨. 센서 수치 행은 아직 확인하지 못함.
커널 로그 21:16:50: CH341이 ttyUSB0에 연결됨.
21:16:53: `interface 0 claimed by ch341 while 'brltty' sets config #1`,
이어서 CH341/ttyUSB0 연결 해제. 따라서 이 EIO는 brltty의 USB 인터페이스
재설정과 연결 해제에 대응한다. 시작 깨진 바이트의 원인은 별도로 미확정.
로컬 85-brltty.rules는 brltty-udev.service를 시작하며,
실행 중 프로세스 명령도 해당 서비스의 ExecStart와 일치했다.

다음 조치: `sudo systemctl mask --runtime --now brltty-udev.service`로
해당 자동 점자장치 서비스를 이번 부팅 동안 중지/차단한 뒤 UNO USB 재연결.
이 조치는 USB 점자장치 자동 지원에 영향을 준다. 패키지 삭제/영구 차단은 하지 않음.
복원은 재부팅 또는 `sudo systemctl unmask --runtime brltty-udev.service` 후
필요한 서비스 재시작. 실제 조치 및 이후 수신 성공 여부는 아직 미검증.

## USB 실측 수신 성공 (21:19 KST)

사용자가 brltty-udev.service runtime mask를 적용한 뒤 USB 재연결 및
`sudo python3 scripts/read_arduino_usb.py --samples 5` 실행 결과를 제공했다.

| UNO time_ms | DS18 °C | DHT22 °C | 습도 % |
|---:|---:|---:|---:|
| 2000 | 결측 | 27.2 | 56.9 |
| 4000 | 27.00 | 27.2 | 56.8 |
| 2000 | 27.00 | 27.3 | 56.8 |
| 4000 | 27.00 | 27.3 | 56.7 |
| 6000 | 27.06 | 27.3 | 56.7 |

수신 시각 UTC 12:19:04.609794~12:19:12.238247.
첫 두 행은 같은 시각에 버퍼에서 읽혔으므로 호스트 수신 간격을 측정 간격으로
해석하지 않는다. 빈 행 2개와 `6000,27.time_ms,...`로 이어진 시작 헤더를
건너뛰었다. 헤더 재등장 및 uptime 감소는 UNO 재시작 흔적이다.
포트 개방에 따른 자동 리셋/시작 버퍼가 원인 후보이나 정확한 트리거는 미확정.
이번에는 EIO가 보고되지 않았고 마지막 세 행은 약 2초 간격으로 모두 유효했다.
실제 전송 성공을 확인했으며, 센서 정확도 교정이나 장시간 안정성 검증은 아니다.
NaN을 0으로 대체하지 않고 결측으로 보존했다.

현재 ch341 로드 및 brltty 차단은 임시 상태다. 재부팅 후 자동 수집하려면
영구 모듈 설치와 CH340에 대한 brltty 충돌 방지 설정을 별도로 완료해야 한다.
