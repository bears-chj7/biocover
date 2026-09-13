# SPI + DHT22 P15 오버레이

이 보드(Jetson Orin Nano Super, R36.4.7)에서 생성한 Jetson-IO 오버레이에 P15 설정을 추가한 소스입니다.
`spi-original.dts`는 변경 전 소스, `spi-dht22.dts`는 적용 후보입니다.
기존 SPI 노드에 변경 없이 P15만 추가했습니다. DS18B20 지원은 포함하지 않습니다.

**현재 상태: 재부팅 후 P15 설정 유지와 응답 펄스 확인. 유효 DHT22 프레임은 미확보.**

다른 세션이 DS18B20 P7 설정을 합쳐 현재 `/boot/ds18b20-pin7.dtbo`를 부팅에 사용합니다. 아래 절차는 그 이전 SPI+DHT22 설치 이력입니다. 이 파일만 재설치하거나 부팅 OVERLAYS를 바꾸면 DS18B20 설정을 잃을 수 있으므로 현재 통합 설정을 먼저 확인해야 합니다.

저장소 루트에서 빌드:

```bash
mkdir -p build
dtc -I dts -O dtb -o build/spi-dht22.dtbo hardware/overlays/spi-dht22.dts
fdtoverlay -i /boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb -o build/validation-only.dtb build/spi-dht22.dtbo
```

`validation-only.dtb`는 병합 검사용이며 부팅 위치에 설치하지 않습니다.

## 수동 적용 순서

아래 단계는 사용자가 한 단계씩 진행하고 결과를 확인합니다.

1. 기존 오버레이 백업:

```bash
sudo cp -n /boot/jetson-io-hdr40-user-custom.dtbo /boot/jetson-io-hdr40-user-custom.dtbo.before-dht22
```

2. 백업 존재와 빌드 성공 확인 후 후보 설치:

```bash
sudo install -m 644 build/spi-dht22.dtbo /boot/jetson-io-hdr40-user-custom.dtbo
```

3. 작업 저장 후 재부팅:

```bash
sudo reboot
```

4. 적용 상태 조회 및 진단:

```bash
sudo grep -i -A 14 'soc_gpio39_pn1' /sys/kernel/debug/pinctrl/2430000.pinmux/pinconf-groups
python3 scripts/check_sensors.py
```

필요하면 백업 오버레이로 복원한 뒤 재부팅합니다:

```bash
sudo cp /boot/jetson-io-hdr40-user-custom.dtbo.before-dht22 /boot/jetson-io-hdr40-user-custom.dtbo
```

Jetson-IO에서 다시 저장하면 수동 추가한 P15 설정이 덮어써질 수 있습니다.
참고: [NVIDIA Jetson 확장 헤더 설정](https://docs.nvidia.com/jetson/archives/r36.3/DeveloperGuide/HR/ConfiguringTheJetsonExpansionHeaders.html).
