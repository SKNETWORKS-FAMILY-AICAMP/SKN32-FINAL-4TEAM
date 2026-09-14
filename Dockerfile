# TrueFit API + 정적 프론트엔드 — 같은 오리진에서 서빙(src/api.py가 frontend/를 마운트).
FROM python:3.11-slim

WORKDIR /app

# psycopg[binary]·argon2-cffi 등은 보통 wheel로 설치돼 별도 빌드 도구가 필요 없다.
# wheel이 없는 아키텍처라 실패하면 여기에 build-essential을 추가한다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY frontend/ ./frontend/
COPY config/ ./config/
COPY data/ ./data/
COPY generated/ ./generated/
COPY db/ ./db/
COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
