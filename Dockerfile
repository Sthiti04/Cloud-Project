FROM grafana/k6:1.4.2 AS loadtool
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && mkdir -p /app/certs \
    && curl --fail --show-error --silent https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /app/certs/rds.pem \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY s23 ./s23
COPY load ./load
COPY --from=loadtool /usr/bin/k6 /usr/bin/k6
USER 10001:10001
EXPOSE 8080 50051
CMD ["python", "-m", "uvicorn", "s23.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
