FROM python:3.14-alpine
WORKDIR /app
COPY . /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt
ENTRYPOINT ["python3"]
CMD ["-m", "gunicorn", "-w", "1", "--threads", "100", "-b", "0.0.0.0:8082", "--chdir", "src", "wsgi:app"]