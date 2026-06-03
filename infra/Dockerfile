FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY ems ./ems
RUN pip install --no-cache-dir ".[all]"
# Příkaz se nastavuje v docker-compose (collector vs api)
CMD ["python", "-m", "ems.collector.main"]
