#!/usr/bin/env python3
"""Generate original, editable SVG wiring diagrams. No external dependencies."""
from html import escape
from pathlib import Path

OUT = Path(__file__).parent
INK, MUTED = '#172b42', '#52677e'
BLUE, GREEN, RED, GRAY, AMBER = '#2463b4', '#16826a', '#bc3345', '#6b7280', '#ac6500'


class SVG:
    def __init__(self, name, title, subtitle, w=1200, h=760):
        self.name, self.w, self.h = name, w, h
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>',
                      '<style>text{font-family:"Noto Sans CJK KR","Noto Sans",Arial,sans-serif}</style>',
                      f'<rect width="{w}" height="{h}" fill="#f5f8fc"/>']
        self.text(40, 49, title, 27, INK, bold=True)
        self.text(40, 79, subtitle, 15)

    def text(self, x, y, text, size=17, color=MUTED, anchor='start', bold=False):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{700 if bold else 400}">{escape(text)}</text>')

    def box(self, x, y, w, h, fill='white', stroke='#d6dfeb', radius=12):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

    def line(self, x1, y1, x2, y2, color=BLUE, dashed=False):
        self.parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="3"'+(' stroke-dasharray="7 5"' if dashed else '')+'/>')

    def dot(self, x, y, color):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')

    def save(self):
        self.text(40, self.h-22, 'BIOCOVER · 2026-09-13 · 개념 배선도 / 실물 축척 아님 · 출처·확인 범위: docs/hardware-guide.md', 13)
        (OUT / self.name).write_text('\n'.join(self.parts) + '\n</svg>\n')


def overview():
    s = SVG('system-overview.svg', '현재 측정 시스템', '실선은 사용 중인 데이터 경로 · 전원 배선은 각 상세 그림 참조', h=700)
    for y, name, sub in [(130,'DS18B20','토양 온도 · UNO D2'), (260,'DHT22 / AM2302','온도·습도 · UNO D3'),
                         (420,'MQ-4 #1 / #2','유입·유출 · CH0 / CH1'), (550,'토양수분 센서','정전용량식 · CH4')]:
        s.box(40,y,300,90)
        s.text(62,y+34,name,22,INK,bold=True); s.text(62,y+65,sub)
    s.box(430,155,280,170,stroke=GREEN)
    s.text(454,197,'Arduino UNO',25,GREEN,bold=True)
    s.text(454,232,'DS18 + DHT22 polling')
    s.text(454,264,'약 2초마다 CSV 전송')
    s.text(454,295,'USB 변환기: CH340',16)
    s.box(430,445,280,155,stroke=BLUE)
    s.text(454,488,'MCP3008',25,BLUE,bold=True)
    s.text(454,525,'8채널 · 10비트 ADC')
    s.text(454,561,'VDD / VREF = 3.3V')
    for a,b in [(175,210),(305,275),(465,480),(595,565)]:
        s.line(340,a,430,b,GREEN if a<400 else BLUE)
    s.box(850,160,310,445,stroke=INK)
    s.text(875,205,'Jetson Orin Nano',25,INK,bold=True)
    s.text(875,239,'Super 개발 키트',21,INK)
    s.text(875,310,'USB: /dev/biocover-uno',16)
    s.text(875,340,'9600 baud · 8N1',16)
    s.text(875,465,'SPI: /dev/spidev0.0',16)
    s.text(875,505,'기본: 화면 출력',19,GREEN,bold=True)
    s.text(875,540,'CSV: 명시적 요청 시 저장',17)
    s.text(875,576,'자동 저장 중지 적용 대기',15,AMBER)
    s.line(710,265,850,265,GREEN); s.text(780,250,'USB',18,GREEN,'middle',True)
    s.line(710,465,850,465,BLUE); s.text(780,450,'SPI',18,BLUE,'middle',True)
    s.text(40,656,'미연결: MQ-4 #3 / #4, CM1106 · P7/P15 직접 센서 통신은 과거 진단 경로',16,AMBER)
    s.save()


def uno():
    s=SVG('uno-sensor-wiring.svg','UNO 센서 핀맵과 풀업 연결','신호 핀은 동작 스케치 확인값 · 아래 5V 전원선은 권장 연결 예시, 현장 전압 재실측은 미수행',h=860)
    for top, name, data, labels in [(120,'DS18B20 방수 프로브','D2',['VDD · 빨강','DQ · 노랑','GND · 검정']),
                                    (460,'DHT22 3핀 모듈','D3',['VCC','DAT / DATA','GND'])]:
        s.box(40,top,220,265,stroke=GREEN)
        s.text(65,top+40,'UNO',26,GREEN,bold=True)
        s.box(870,top,290,265)
        s.text(894,top+40,name,21,INK,bold=True)
        for offset, pin, end, color in zip([85,165,225],['5V',data,'GND'],labels,[RED,BLUE,GRAY]):
            y=top+offset
            s.text(230,y+6,pin,19,color,'end',True)
            s.line(260,y,870,y,color)
            s.text(894,y+6,end,18,color)
        if data=='D2':
            s.line(570,top+85,570,top+103,RED)
            s.box(557,top+103,26,43,'white',BLUE,0)
            s.line(570,top+146,570,top+165,BLUE)
            s.dot(570,top+85,RED); s.dot(570,top+165,BLUE)
            s.text(610,top+132,'4.7kΩ 풀업',20,BLUE,bold=True)
            s.text(65,top+303,'노란선과 D2는 직접 연결. 저항은 DATA–5V 사이에 분기 연결하며 직렬로 넣지 않습니다.',17)
        else:
            s.text(395,top+123,'모듈 내장 풀업 있음: 추가 저항 없음',18,BLUE)
            s.text(894,top+258,'실크 인쇄로 핀 식별',15,AMBER)
    s.text(40,778,'UNO ↔ Jetson은 USB로 연결. UNO의 5V DATA를 Jetson 헤더에 직접 연결하지 않습니다.',17,RED)
    s.text(40,808,'위·아래 UNO 박스는 같은 보드의 5V/GND를 반복 표시한 것입니다. 선 색은 기능 구분입니다.',15)
    s.save()


def jetson():
    s=SVG('jetson-header.svg','Jetson 40핀 헤더 사용 현황','물리 핀 번호 P1~P40 · P1–P2를 위에 놓은 도식 · 실제 보드의 P1 표시를 먼저 확인',h=1120)
    s.box(475,115,250,895,'#e9eff7')
    left={1:('3.3V → ADC / 토양수분',RED),3:('I2C · 미사용',GRAY),5:('I2C · 미사용',GRAY),
          7:('GPIO09 · 과거 DS18 직결',AMBER),9:('GND',GRAY),11:('미사용',GRAY),13:('미사용',GRAY),
          15:('GPIO12 · 과거 DHT22 직결',AMBER),17:('3.3V · 현재 센서 사용 없음',RED),
          19:('MOSI → MCP3008 DIN',BLUE),21:('MISO ← MCP3008 DOUT',BLUE),23:('SCK → MCP3008 CLK',BLUE),
          25:('GND',GRAY),27:('I2C · 미사용',GRAY),29:('미사용',GRAY),31:('미사용',GRAY),33:('미사용',GRAY),
          35:('미사용',GRAY),37:('미사용',GRAY),39:('GND',GRAY)}
    right={2:('5V → MQ-4 #1 / #2',RED),4:('5V · 예비',RED),6:('GND · ADC / 센서 공통',GRAY),
           8:('UART TX · CM1106 미연결',GRAY),10:('UART RX · CM1106 미연결',GRAY),12:('미사용',GRAY),
           14:('GND',GRAY),16:('미사용',GRAY),18:('미사용',GRAY),20:('GND',GRAY),22:('미사용',GRAY),
           24:('CS0 → MCP3008 CS/SHDN',BLUE),26:('CS1 · 설정 유지 / 미배선',GRAY),28:('I2C · 미사용',GRAY),
           30:('GND',GRAY),32:('미사용',GRAY),34:('GND',GRAY),36:('미사용',GRAY),38:('미사용',GRAY),40:('미사용',GRAY)}
    for i in range(20):
        y=145+i*43
        for n,x,table,tx,anchor in [(2*i+1,550,left,450,'end'),(2*i+2,650,right,750,'start')]:
            label,col=table[n]
            s.box(x-27,y-18,54,32,'white',col,5)
            s.text(x,y+5,str(n),18,col,'middle',True)
            s.text(tx,y+5,label,16,col,anchor)
    s.text(40,1040,'P7 / P15: TXB0108 경유 → DS18/DHT22는 현재 UNO에서 읽습니다.',18,AMBER)
    s.text(40,1072,'표의 “미사용”은 프로젝트 사용 현황이며 GPIO 모드나 핀mux 설정값을 의미하지 않습니다.',15)
    s.save()


def adc():
    s=SVG('mcp3008-pinmap.svg','MCP3008 핀맵과 Jetson SPI 연결','16핀 PDIP / SOIC: 부품 윗면, 홈이 위쪽 · 모듈 기판 사용 시 실크 인쇄와 제조사 회로 확인',h=850)
    s.box(465,135,270,455,'#e5edf7',INK)
    s.parts.append('<path d="M570,135 A30,25 0 0 0 630,135" fill="white" stroke="#172b42" stroke-width="2"/>')
    s.text(600,202,'MCP3008',23,INK,'middle',True)
    llabels=['MQ-4 #1 → CH0','MQ-4 #2 → CH1','CH2 · #3 예정 / 미연결','CH3 · #4 예정 / 미연결',
             '토양수분 → CH4','CH5 · 미사용','CH6 · 미사용','CH7 · 미사용']
    rlabels=['VDD → P1 (3.3V)','VREF → P1 (3.3V)','AGND → GND','CLK ← P23',
             'DOUT → P21','DIN ← P19','CS/SHDN ← P24','DGND → GND']
    for i in range(8):
        y=242+i*43
        lcol=GREEN if i in (0,1,4) else GRAY
        rcol=RED if i<2 else GRAY if i in (2,7) else BLUE
        s.line(395,y,465,y,lcol); s.text(485,y+6,str(i+1),19,lcol,bold=True)
        s.text(375,y+6,llabels[i],17,lcol,'end')
        s.line(735,y,805,y,rcol); s.text(715,y+6,str(16-i),19,rcol,'end',True)
        s.text(825,y+6,rlabels[i],17,rcol)
    s.box(40,630,1120,145,'#fff8e9','#d5a756')
    s.text(62,667,'아날로그 입력: 0~3.3V 범위로 제한',22,AMBER,bold=True)
    s.text(62,703,'MQ-4 전원은 5V. AOUT 최대 전압과 분압 설치 여부는 미확인입니다.',18,INK)
    s.text(62,737,'그림의 CH0/CH1 경로는 채널 배정입니다. 5V AOUT 직결을 권장하는 배선도가 아닙니다.',17,INK)
    s.text(40,811,'SPI는 /dev/spidev0.0 · 토양수분은 CH2에서 CH4로 이동 · VREF는 실측 전까지 공칭 3.3V',15)
    s.save()


if __name__=='__main__':
    for draw in (overview,uno,jetson,adc):
        draw()
