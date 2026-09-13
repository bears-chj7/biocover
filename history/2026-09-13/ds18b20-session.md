# DS18B20 세션 및 설치 후 검증

## 목표와 번호 체계

물리 P7에 DS18B20을 연결하고 기존 SPI와 DHT22 P15를 유지합니다.

| 구분 | 값 |
|---|---|
| 보드 / OS | Jetson Orin Nano Super / L4T 36.4.7 |
| 실행 커널 | 5.15.148-tegra |
| 커널 빌드 설정 | `# CONFIG_W1 is not set` |
| 헤더 물리 핀 | P7 / GPIO09 |
| SoC 핀 | PAC.06 |
| 디바이스 트리 GPIO specifier | 166 (`0xa6`) |
| gpiochip0 line offset | 144 (DT 번호 166과 다른 번호 체계) |
| 이번 커널 로그의 전역 GPIO 번호 | 492 (커널별로 고정하지 않음) |
| pinmux / function | soc_gpio59_pac6 / rsvd2 |
| 원래 작업 경로 | /home/judgejack/project/ds18b20 |

DS18B20 VDD→3.3V, GND→공통 접지, DATA→P7, DATA–3.3V 4.7kΩ 풀업이 필요합니다. 실제 풀업 장착·모듈 내장 여부는 아직 검증하지 않았습니다.

## A. 다른 세션의 준비 작업 (사용자 인계 + 로컬 파일 확인)

1. 기본 모듈이 없어 modprobe가 실패한 원인을 확인했습니다.
2. Linux stable v5.15.148의 W1 소스를 설치된 NVIDIA 커널 헤더와 Module.symvers로 외부 모듈 빌드했습니다.
   - `w1/wire.ko`
   - `w1/masters/w1-gpio.ko`
   - `w1/slaves/w1_therm.ko`
3. 모듈 vermagic이 현재 커널과 일치합니다. 빌드에 사용한 Makefile과 파일 해시는 보관했습니다.
4. 기존 SPI+DHT22 오버레이를 기반으로 onewire와 hdr40-pin7을 추가했습니다. GPIO 라이브러리의 오픈드레인 에뮬레이션을 사용합니다.
5. 기존·신규 오버레이를 같은 DTB에 각각 적용해 비교했습니다. 비교 기록에는 onewire와 P7만 추가되며 P15·SPI는 유지됩니다.
6. `install.py`, `read_temperature.py`, README와 overlay-validation.diff를 작성하고 Python 문법을 검사했습니다.

소스 출처는 다른 세션 README의 [Linux stable v5.15.148 W1](https://github.com/gregkh/linux/tree/v5.15.148/drivers/w1)입니다. 현재 history 작성 세션은 업스트림과 모든 소스의 바이트 일치까지 다시 검증하지 않았습니다.

다른 세션이 종료할 때는 sudo 암호 요구로 **설치·부팅 변경·재부팅을 수행하지 않았고 모듈 로드와 센서 동작도 미검증**이었습니다.

## B. 설치 스크립트의 실제 동작

보관된 소스를 읽어 확인한 동작입니다. 스크립트 실행 로그 전체를 확보한 것은 아닙니다.

- root 권한과 커널 버전 확인.
- 현재 extlinux.conf와 헤더 오버레이가 준비 당시 사본과 동일한지 확인; 다르면 중단.
- 각 모듈 vermagic 확인.
- `/boot/ds18b20-backup-YYYYMMDD-HHMMSS`에 부팅 설정과 기존 SPI+DHT22 오버레이 백업.
- `/lib/modules/5.15.148-tegra/extra/ds18b20`에 모듈 설치, depmod, w1-gpio 및 w1-therm modprobe.
- `/boot/ds18b20-pin7.dtbo` 복사 후 extlinux의 오버레이 경로 변경.
- 자동 재부팅 없음. 원래 헤더 오버레이 보존.

설치 스크립트는 준비 당시 설정과 비교하므로 현재 설치 후 상태에서 재실행하면 중단할 수 있습니다. 스크립트의 modprobe는 그 실행 시점의 로드이며 재부팅 후 w1_therm 로드를 보장하는 서비스 설정이 아닙니다.

## C. 이후 사용자 설치·재부팅과 직접 확인한 증거

사용자가 설치 후 재부팅 완료를 보고했습니다. 현재 센서 세션은 다음을 직접 확인했습니다.

- 백업 디렉터리: `/boot/ds18b20-backup-20260913-171755`.
- 현재 OVERLAYS: `/boot/ds18b20-pin7.dtbo`.
- 준비본과 설치본 SHA256 동일: `fa181519c6a2e5695d181e1812b3d4347b7d227fa7e2302c11672a40658c8efb`.
- 기존 SPI+DHT22 오버레이와 별도 before-dht22 백업도 보존.
- 활성 DT에서 P7·P15·SPI 노드 확인.
- wire 및 w1_gpio 로드, w1_bus_master1 생성.
- w1_therm.ko 설치와 vermagic 확인. **재부팅 후 점검 시 w1_therm은 로드되지 않음**.

커널 본체의 CONFIG_W1이 비활성인 채로 외부 모듈을 빌드·설치한 방식입니다. OS 전체 커널을 W1 지원으로 재빌드했다고 기록하지 않습니다.

## D. 센서 인식: 아직 실패

정상 DS18B20 family 0x28 ID나 온도 파일은 나타나지 않았습니다. 대신 `00-800000000000`, `00-400000000000`, `00-c00000000000`, `00-200000000000`, `00-a00000000000` 등이 탐색 때마다 바뀌었습니다. 이후 이력 작성 시에도 `00-100000000000`, `00-900000000000`, `00-e00000000000`만 관찰했습니다.

주요 로그:

```text
wire: module verification failed: signature and/or required key missing - tainting kernel
gpio-492 (onewire): enforced open drain please flag it properly in DT/ACPI DSDT/board file
w1_search: max_slave_count 64 reached, will continue next search.
Family 0 ... is not registered.
```

서명 관련 로그는 로드 실패와 동일하지 않습니다. 실제 wire·w1_gpio는 로드됐습니다. 반면 버스가 만들어졌다는 사실만으로 센서 동작이 검증된 것은 아닙니다. w1_therm을 로드하는 것만으로 잘못 탐색되는 family 0 문제까지 해결된다고 단정하지 않습니다.

현재 판정: **빌드·설치·버스 생성 확인 / DS18B20 센서 인식·CRC·온도 미검증**.

## E. 남은 점검과 복원 범위

다음으로 P7 실제 pinconf, 전원·DATA·공통 GND·4.7kΩ 풀업, 신호 타이밍을 확인합니다. P7은 w1-gpio가 사용하는 중이므로 별도 프로그램이 동시에 구동하지 않도록 합니다.

부팅 복원은 설치 백업의 extlinux.conf를 사용하면 설치 직전 SPI+DHT22 경로로 되돌릴 수 있지만, **설치된 외부 모듈을 제거하는 전체 롤백은 아닙니다**. 현재 부팅 파일이 추가 변경됐으면 먼저 새 백업과 차이를 확인해야 합니다. 실제 복원은 수행하지 않았습니다.

과거 안내 명령 `sudo python3 /home/judgejack/project/ds18b20/install.py`는 이력이며 지금 다시 실행하라는 지시가 아닙니다. 센서가 정상 인식된 뒤에는 원래 작업 경로의 read_temperature.py로 CRC 확인 온도를 읽을 수 있습니다.

## F. history 정리 중 사용자 추가 조회

사용자가 전달한 실제 pinconf는 [원문](artifacts/pin7-pinconf-user.txt)에 보관했습니다.
`pull=0`, `tristate=0`, `enable-input=1`, `function=rsvd2`, `gpio-mode=0`, `open-drain=0`입니다.
의도한 P7 pinmux 필드는 반영되어 있습니다. 하드웨어 open-drain 비트와 GPIO 라이브러리의 오픈드레인 에뮬레이션을 구분해야 하므로 open-drain=0만으로 실패 원인이라고 결론내리지 않습니다.
이 조회는 풀업 저항의 실제 장착이나 DATA 파형을 확인한 결과가 아닙니다. 정상 ID 탐색 문제는 미해결입니다.

## G. 사용자 확인: 풀업 저항 미연결

사용자가 DS18B20을 ‘DS18’로 줄여 부르기로 했으며 DATA 풀업 저항이 연결되지 않았다고 확인했습니다.
이는 기존 저항 유무 미확인을 갱신하는 진술입니다. DATA–3.3V 사이 4.7kΩ 추가를 안내했고, 실제 연결·재검사 완료는 아직 아닙니다.
현재 3선 외부전원 구성은 VDD→P1 3.3V, DQ→P7, GND→P6입니다. 저항은 P1 3.3V와 P7/DQ 신호 접점 사이에 연결합니다. 직렬 저항이 아니며 극성은 없습니다.
전원을 종료·분리한 뒤 배선하고, DATA를 5V로 풀업하지 않도록 안내합니다.
근거: [DS18B20 데이터시트 Figure 7](https://www.analog.com/media/en/technical-documentation/data-sheets/ds18b20.pdf).

## H. 사용자 풀업 연결 후 재점검 (18:33 전후 KST)

사용자가 안내한 풀업 저항 연결을 완료했다고 보고했습니다. Jetson uptime 약 6분으로 재부팅된 환경에서 확인했습니다.
`wire`, `w1_gpio`가 로드되어 있고 P7 gpiochip0 line144는 onewire/open-drain으로 사용 중입니다. 활성 DT의 P7 tristate=0/input=1/rsvd2 설정도 유지됩니다.
이번에는 이전의 00-… ID가 없으며 `w1_master_slave_count=0`, `w1_master_slaves=not found.`입니다. 조회 시 탐색 시도는 40회, search=-1(계속 탐색)이었습니다. 정상 28-… 센서와 온도는 아직 없습니다.
이번 부팅 로그에는 이전의 family0 가짜 ID·max_slave_count 오류가 관찰되지 않았습니다. 풀업 추가 후 탐색 양상이 달라졌으나 센서 통신 성공을 뜻하지 않습니다.
다음은 DS18 DATA–GND 실제 전압 확인으로 풀업 경로와 신호 상태를 검증합니다. 이 점검 중 P7/드라이버 설정 변경은 하지 않았습니다.
