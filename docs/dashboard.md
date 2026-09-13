# 로컬 센서 웹 대시보드

Jetson 자체에서는 **http://127.0.0.1:8080**, 다른 기기에서는
**http://192.168.123.101:8080**으로 접속한다(2026-09-13 현재 LAN IP).
서버는 기본 0.0.0.0:8080에서 IPv4 접속을 받는다. 로그인은 없다. 외부 CDN 없이 로컬 CSS/JavaScript/Canvas를 사용한다.

## 설치 및 실행

현재 환경에서 Flask 3.1.2 설치를 확인했다. 다른 환경의 의존성은
`web/requirements.txt`에 기록했다. 실행 중인 CH340 드라이버와 기존 UNO udev 규칙을 사용한다.

```bash
sudo python3 scripts/install_dashboard.py
```

설치기는 기존 `biocover-uno.service` 자동 CSV 수집을 중지/비활성화하고
`biocover-web.service`를 설치하되 중지/비활성화 상태로 둔다. 서비스는 judgejack 권한과 gpio 보조 그룹으로
실행한다. 부팅 및 서비스 오류 후 자동 실행하지 않으며 사용자가 직접 시작한다. **시작 버튼을 누르기 전에는 측정 CSV가 없다.**
기존 웹 서비스 파일이 있으면 `/var/backups/biocover/UTC시각/`에 백업한다.
사용자가 관리자 비밀번호를 입력해야 하며 에이전트의 sudo -n 시도는 실패했다.
이 문서 작성 시점에서 시스템 설치/실제 센서 웹 수신 검증은 대기 상태다.

수동 실행은 기존 수집 서비스를 먼저 중지한 다음:

```bash
python3 web/app.py
```

기본 포트 8080, 데이터 폴더 data/web. `--port`와 `--data-dir`로 변경 가능하다.
동일 폴더로 두 서버를 실행하면 잠금으로 거부한다. 설치 서비스와 수동 서버를 동시에
실행하지 않는다. 앱은 가짜/예제 값을 센서값 대신 표시하지 않는다.

## 화면과 측정 동작

- 시작: 새 세션, 최신 UNO 캐시 + 그 시점의 ADC 읽기. 즉시 첫 행,
  이후 5초마다 갱신. 첫 UNO 응답 전에는 해당 항목을 결측으로 기록한다.
- 일시정지: CSV/로그/그래프 추가를 멈춘다. UNO 입력은 계속 받아 최신값을 유지한다.
- 재개: 같은 세션 파일에 최신값부터 이어 기록한다. 정지 구간을 소급해 채우지 않는다.
- 정지: 파일을 마무리하고 다운로드 목록에 표시한다. 다음 시작은 새 세션이다.
- 센서 6개 항목: DS18 온도, DHT22 온도/습도, MQ-4 #1/#2 raw, 토양수분 raw.
  ADC는 공칭 VREF 3.3V 전압도 표시한다. ppm/수분 % 보정은 하지 않는다.
- 미연결 MQ-4 #3/#4와 CM1106은 별도 표시한다.
- 집계: 세션 전체의 유효값만으로 평균/최솟값/최댓값 계산. 결측은 제외한다.
- 그래프: 최근 5/10/30분 선택. 표시 범위 밖 값은 왼쪽으로 빠져나간다.
  결측과 일시정지 구간을 선으로 연결하지 않는다.
  토양 온도·공기 온도·습도·MQ-4 #1·MQ-4 #2·토양수분을 각각 분리하여
  한 행에 한 계열씩 총 6개 그래프로 표시한다. 모바일에서도 단일 열을 유지하고
  시간축 눈금 수를 줄여 겹침을 방지한다.
- 로그: 최신순 120행의 스크롤 영역. 서버 메모리는 최근 720행으로 제한하며
  화면에서 사라진 행도 CSV에는 남는다.
- 브라우저 새로고침은 서버 세션을 유지한다. 모든 브라우저는 같은 측정 세션을 본다.
  브라우저 연결이 45초 넘게 끊기면 세션을 정지하고 저장한다.
  장시간 백그라운드 탭의 타이머 제한도 연결 단절로 처리될 수 있다.

UNO는 약 2초 주기로 수신하고, 마지막 수신이 6초보다 오래되면 이전 값을 재사용하지 않는다.
USB 연결 오류나 ADC 오류는 해당 그룹의 결측으로 기록한다. 정상 형식의 숫자가
센서 교정 정확도를 보장하지는 않는다. 웹 화면은 2초마다 상태를 조회하지만
측정/CSV/로그의 새 행은 5초마다 하나다.

## CSV와 비정상 종료

진행 중: `data/web/session-YYYYMMDDTHHMMSS.ffffffZ.partial.csv`.
정상 정지: 같은 타임스탬프의 `.csv`. 서버 재시작 시 남은 부분 파일은
끝의 불완전 행을 제거하고 `-recovered.csv`로 바꾼다. 복구 후 자동 측정 재개는 하지 않는다.
파일명/CSV 시각은 UTC이며 화면 시각은 브라우저 시간대다.

각 측정 행마다 flush + fsync하고, 파일 이름 변경 후 디렉터리도 fsync한다.
SIGTERM/일반 종료 시 세션을 마무리한다. SIGKILL은 다음 실행에서 복구하며
마지막 완료된 기록까지 유지한다. 전원 차단 중 진행하던 행과 저장장치 자체의
장애까지 보장할 수는 없다. 저장 오류 시 측정 상태를 오류로 전환한다.
파일 보존 기간/자동 삭제는 설정하지 않았으므로 디스크 사용량을 관리한다.

CSV 열: timestamp, sequence, elapsed_s, ds18, temperature, humidity,
mq1, mq2, soil, mq1_v, mq2_v, soil_v, uno_received_at, uno_time_ms,
uno_age_s, uno_status, adc_status, errors.
elapsed_s는 일시정지를 포함한 세션 경과 시간이다. UNO time_ms는 별도 기기의 uptime이다.
기존 data/arduino 파일은 보존하지만 대시보드 세션 목록은 data/web만 표시한다.

## 검증

```bash
python3 -m unittest discover -s tests -p test_dashboard.py -v
node --check web/static/app.js
```

자동 검증: 시작 전 미저장, 중복 시작 거부, 일시정지/재개/정지, CSV 행과 통계,
파일 다운로드, 다른 출처의 제어 요청 차단, 브라우저 단절 종료, UNO 데이터 신선도,
실제 자식 프로세스 SIGKILL 후 CSV 복구. 센서값은 테스트에서만 합성 입력을 사용한다.

6개 unittest와 Python/JavaScript/systemd 문법 검증을 통과했다.
현재 로컬 Chromium의 Snap/GLIBC/ICU 실행 오류로 브라우저 화면 캡처는 완료하지 못했다.
설치 후 실제 화면과 실측 수신의 최종 확인이 필요하다.

## 서비스 관리

설치는 한 번만 수행한다. 이미 자동 실행으로 설치했으면 아래 명령을 한 번 실행한다.

```bash
sudo systemctl disable --now biocover-web.service
```

필요할 때 시작하고 브라우저에서 http://127.0.0.1:8080 을 연다.

```bash
sudo systemctl start biocover-web.service
```

사용을 마치면 화면의 정지 버튼으로 측정을 종료한 뒤 웹서버도 중지할 수 있다.
서비스 중지 자체도 진행 중 CSV를 마무리한다.

```bash
sudo systemctl stop biocover-web.service
```


```bash
systemctl status biocover-web.service --no-pager
journalctl -u biocover-web.service -n 30 --no-pager
sudo systemctl disable --now biocover-web.service
```

웹서버를 중지해도 기존 CSV를 삭제하지 않는다. 독립 센서 스크립트 실행 전
웹 측정 세션을 정지해서 USB 포트를 반환한다.
구현 참고: [Flask 공식 문서](https://flask.palletsprojects.com/en/stable/quickstart/).

## 다른 기기에서 IP로 접속

현재 Wi-Fi 주소는 `192.168.123.101/24`이며 DHCP에 따라 바뀔 수 있다.
주소 확인은 `ip -br address`. `0.0.0.0`은 서버가 듣는 주소이며 브라우저에 입력할 주소가 아니다.
로컬 접속만 원하면 수동 실행 시 `python3 web/app.py --host 127.0.0.1` 사용.
IP 주소 요청은 허용하고, 다른 웹사이트가 보내는 제어 요청은 계속 거부한다.
로그인이 없으므로 접속 가능한 기기는 같은 측정 세션을 제어하고 CSV를 내려받을 수 있다.

이전 실행 프로세스는 재시작해야 수정이 반영된다. 아래 명령은 서버 재시작 후
리스닝 주소, 자기 IP HTTP 응답, UFW 및 INPUT 규칙을 조회한다. 방화벽은 변경하지 않는다.
진행 중인 측정은 서비스 재시작으로 저장·종료된다.

```bash
sudo python3 scripts/check_web_network.py
```

자기 IP 요청 성공은 다른 기기에서의 접속 성공을 증명하지 않는다.
같은 네트워크의 기기에서 직접 접속해 확인한다. 공유기 밖 인터넷에서의 접속은
별도 라우팅/포트 전달이 필요하며 이 작업에서는 공유기 설정을 변경하지 않았다.
방화벽 조회는 에이전트의 sudo 비밀번호 요구로 아직 미완료다.
