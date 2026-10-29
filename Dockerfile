FROM python:3.14-alpine
# Logs printed by the API (lite_logging), chosen at build time:
#   docker build --build-arg DEBUG=true --build-arg INFO=false -t sadikoi-api .
# WARNING, ERROR and CRITICAL are always printed.
ARG DEBUG=false
ARG INFO=true
# PYTHONUNBUFFERED: logs are written right away, so they reach `docker logs` and sadikoi-logs immediately.
ENV DEBUG=$DEBUG \
    INFO=$INFO \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt
ENTRYPOINT ["python3"]
CMD ["-m", "gunicorn", "-w", "1", "--threads", "100", "-b", "0.0.0.0:8082", "--chdir", "src", "wsgi:app"]
