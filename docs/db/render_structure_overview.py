"""Render the v4 database hierarchy as matching landscape PNG and SVG files."""
from pathlib import Path
from html import escape
import re
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
SPEC = (OUT / 'table_spec.md').read_text(encoding='utf-8-sig')
groups = [
    ('config', '도메인 정의', ['도메인', '도메인 정의 버전']),
    ('identity', '사용자와 대화', ['사용자', '사용자 설정', '대화', '메시지']),
    ('shared', '공통 기준', ['단위']),
    ('planning', '구매 계획', ['계획', '계획 버전', '조건', '그룹 / 슬롯', '필요 항목', '보유 물품', '구매 항목', '충족 연결']),
    ('catalog', '상품과 가격', ['상품', '옵션', '분류', '분류 연결', '근거 속성', '판매처', '판매 제안', '가격 / 재고 관측']),
    ('assets', '상품 자료 관리', ['파일 객체', '상품 자료', '자료 버전', '적용 상품 연결']),
    ('rag', '자료 검색', ['추출 작업', '청크', '임베딩 설정', '청크 벡터', '검색 실행', '검색 결과']),
    ('community', 'PC 구성과 리뷰', ['사용자 PC', '구성 버전', '구성 부품', '작성 리뷰', '리뷰 본문 버전']),
    ('evidence', '근거와 리뷰 통계', ['출처', '인용 근거', '리뷰 대상', '리뷰 요약', '리뷰 집계', '집계 구성원']),
    ('engine', '추천과 검증', ['추천 실행', '추천 후보', '후보 근거', '검사 결과', '검사 대상', '검사 근거', '사용자 행동 기록']),
    ('notification', '가격 추적과 알림', ['가격 추적', '가격 판정', '알림 이벤트']),
    ('dataset', '리뷰 학습 데이터', ['생성 실행', '실제 / 합성 표본', '라벨 정의', '정답 / 검수 이력']),
]
tables = re.findall(r'^\| \d{2} \| \[([\w]+)\.[^\]]+\]', SPEC, re.M)
assert len(tables) == sum(len(g[2]) for g in groups) == 58
assert all(tables.count(name) == len(items) for name, _, items in groups)

W, H = 3360, 1160
image = Image.new('RGB', (W, H), '#f8fafc')
draw = ImageDraw.Draw(image)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
       '<title id="title">데이터베이스 → 스키마 → 테이블 전체 구조</title>',
       '<desc id="desc">PostgreSQL 데이터베이스 하나 아래 12개 스키마와 총 58개 테이블을 가로로 배치한 소속 관계도. 파일 원본은 별도 객체 저장소에 보관한다.</desc>',
       f'<rect width="{W}" height="{H}" fill="#f8fafc"/>']

def rect(x, y, w, h, fill, stroke=None, radius=12):
    draw.rounded_rectangle((x, y, x+w, y+h), radius, fill=fill, outline=stroke, width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke or "none"}" stroke-width="2"/>')

def line(points, color='#94a3b8', width=3, dashed=False):
    if dashed:
        (x1,y1),(x2,y2)=points
        for x in range(int(x1), int(x2), 16):
            draw.line((x,y1,min(x+8,x2),y2), fill=color, width=width)
    else:
        draw.line(points, fill=color, width=width)
    dash = ' stroke-dasharray="8 8"' if dashed else ''
    svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}"{dash}/>')

def text(x, y, value, size=25, color='#24364b', bold=False, center=False):
    font=ImageFont.truetype('C:/Windows/Fonts/malgunbd.ttf' if bold else 'C:/Windows/Fonts/malgun.ttf',size)
    assert draw.textlength(value, font=font) < W-120
    draw.text((x,y),value,font=font,fill=color,anchor='mt' if center else 'lt')
    svg.append(f'<text x="{x}" y="{y+size}" text-anchor="{"middle" if center else "start"}" font-family="Malgun Gothic, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(value)}</text>')

text(60,35,'데이터베이스 전체 구조',44,bold=True)
text(60,96,'테이블 명세서 v4 기준  ·  소속 관계도 — 외래키 연결은 생략',24,color='#617287')
rect(1280,155,800,128,'#163d50')
text(1680,177,'데이터베이스 1개',30,color='#ffffff',bold=True,center=True)
text(1680,225,'PostgreSQL + pgvector  ·  12개 스키마 / 58개 테이블',24,color='#d9edf4',center=True)
rect(2470,165,820,110,'#ffffff','#b7c5cf')
text(2880,180,'별도 객체 저장소 · DB 외부',27,bold=True,center=True)
text(2880,224,'파일 원본·파생 이미지·비공개 데이터셋 산출물',23,center=True)
line([(2080,218),(2470,218)],dashed=True)
text(2275,177,'위치·메타데이터 참조',21,color='#617287',center=True)

start, gap, cardw = 60, 20, 250
centers=[start+i*(cardw+gap)+cardw/2 for i in range(12)]
line([(1680,283),(1680,340)])
line([(centers[0],340),(centers[-1],340)])
text(60,294,'01  DATABASE → 02  SCHEMA',21,bold=True,color='#617287')
for i,(name,role,items) in enumerate(groups):
    x=start+i*(cardw+gap); cx=x+cardw/2
    line([(cx,340),(cx,382)])
    rect(x,382,cardw,118,'#e4eef5','#bacddb')
    text(cx,397,name,26,bold=True,center=True)
    text(cx,439,f'{role} · {len(items)}개',21,center=True)
    line([(cx,500),(cx,555)])
    rect(x,555,cardw,416,'#ffffff','#d3dce4')
    text(x+20,571,'TABLES',17,bold=True,color='#718396')
    for j,item in enumerate(items):
        font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',23)
        assert draw.textlength(item,font=font) <= cardw-40, item
        text(x+20,613+j*42,item,23)

text(60,518,'03  TABLE',21,bold=True,color='#617287')
line([(60,1010),(3300,1010)],color='#d3dce4',width=2)
text(60,1039,'읽는 법',24,bold=True)
text(200,1039,'위: 데이터베이스  →  가운데: 업무별 스키마  →  아래: 소속 테이블',24)
text(60,1092,'파일은 객체 저장소에, 관계·버전·검색 벡터는 PostgreSQL에 저장합니다.',23,color='#617287')
svg.append('</svg>')
image.save(OUT/'database-structure-overview.png')
(OUT/'database-structure-overview.svg').write_text('\n'.join(svg),encoding='utf-8')
print('Saved PNG and SVG: 3360 × 1160; 12 schemas, 58 tables verified.')
