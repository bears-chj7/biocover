# 증거 파일과 원본 범위

- `ds18b20-session/`: 다른 세션의 작성 파일을 그대로 복사한 이력 사본입니다. README의 ‘미설치·미검증’과 절대 경로는 당시 원문을 보존했습니다.
- `install.py`: **보관용이며 이 위치에서 실행하지 않습니다.** 원래 디렉터리의 빌드 결과·original.dtbo 등에 의존합니다. 현재 시스템은 이미 설치 후 상태입니다.
- `read_temperature.py`: 원본 CRC 확인 읽기 코드 사본. 문법 검사만으로 센서 동작이 검증되지는 않습니다.
- `external-modules.Makefile`: 원본 w1/Makefile의 이름을 바꾼 사본입니다.
- `original-spi-dht22.dts`: 다른 세션의 original.dtbo를 dtc로 역변환한 자료입니다. 원래 사람이 작성한 소스라고 주장하지 않습니다.
- `overlay-validation.diff`: 다른 세션이 작성한 기존/통합 DT 차이 기록입니다.
- `extlinux.after-install.conf`: history 작성 시 읽은 실제 부팅 설정.
- `extlinux.backup-171755.conf`: 실제 설치 백업 디렉터리의 extlinux.conf 사본.
- `manifest.json`: 수집 시각, 원래 경로, 파일 크기·SHA256, 모듈 vermagic. 수집하지 못한 파일은 오류로 표시합니다.

커널 업스트림 소스 전체·헤더·Module.symvers·빌드 산출물(.ko/.o/.dtb/.dtbo)은 Git에 중복 저장하지 않았습니다. 원본 작업 경로와 소스 출처, 주요 소스·모듈 해시는 기록했습니다. 따라서 이 사본만으로 재설치/완전 재현이 가능하다고 보장하지 않습니다. 커널 업데이트 시 빌드 환경과 모듈을 다시 검증해야 합니다.

바이너리 설치본과 준비본의 동일성은 manifest로 확인할 수 있으나 센서의 물리적 정상 동작은 별도의 측정이 필요합니다.
