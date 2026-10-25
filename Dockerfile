FROM python:3.14-alpine
WORKDIR /app
COPY . /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt
ENTRYPOINT ["python3"]
CMD ["src/app.py"]