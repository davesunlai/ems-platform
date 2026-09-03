# EMSBOX agent — multi-arch (arm64/amd64). Build z KOŘENE repa:
#   docker build -f emsbox/Dockerfile -t teraems/emsbox-agent .
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY ems ./ems
COPY emsbox ./emsbox
RUN pip install --no-cache-dir httpx pymodbus pydantic fastapi uvicorn pyyaml pyserial
VOLUME /data
ENV EMSBOX_CRED=/data/credentials.json EMSBOX_BUFFER=/data/buffer.db EMSBOX_CONFIG_CACHE=/data/config.json
CMD ["python", "-m", "emsbox.agent", "run"]
