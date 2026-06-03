FROM python:3.12-slim
WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=120
COPY pyproject.toml ./
COPY ems ./ems
RUN pip install --no-cache-dir --retries 5 --timeout 120 ".[all]"
# Příkaz se nastavuje v docker-compose (collector vs api)
CMD ["python", "-m", "ems.collector.main"]
