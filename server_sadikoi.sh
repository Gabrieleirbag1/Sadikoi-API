#!/bin/bash

# Manages the "sadikoi-api" Docker container.
#
# Usage:
#   ./server_docker.sh [option]
#
# Options:
#   (no option)       Start the container in detached mode.
#   -it               Start the container in interactive mode.
#   -s                Stop the container.
#   -r                Restart the container.
#   -m [command...]   Run src/manage.py in a one-off container (default command: migrate).
#                     Run it once before the first start: the API doesn't create the database itself.
#                     Examples: ./server_docker.sh -m
#                               ./server_docker.sh -m showmigrations
#                               ./server_docker.sh -m rollback
#
# Port 8082 on the host is mapped to port 8082 in the container.
# Volumes (kept on the host, so they survive the --rm containers):
#   - $HOST_INSTANCE_DIR -> $APP_DIR/instance     (SQLite database)
#   - $HOST_UPLOADS_DIR  -> $APP_DIR/src/uploads  (uploaded profile pictures)

CONTAINER_NAME="sadikoi-api"
IMAGE="sadikoi-api:latest"
# Working directory of the image (where src/ and instance/ live).
APP_DIR="/app"

# Host folders, next to this script by default (override with environment variables).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_INSTANCE_DIR="${HOST_INSTANCE_DIR:-$SCRIPT_DIR/instance}"
HOST_UPLOADS_DIR="${HOST_UPLOADS_DIR:-$SCRIPT_DIR/src/uploads}"

# Created here, not by Docker: Docker would create missing folders owned by root.
mkdir -p "$HOST_INSTANCE_DIR" "$HOST_UPLOADS_DIR"

VOLUMES=(
    -v "$HOST_INSTANCE_DIR:$APP_DIR/instance"
    -v "$HOST_UPLOADS_DIR:$APP_DIR/src/uploads"
)

start_detached() {
    sudo docker run -d --rm --name "$CONTAINER_NAME" -p 8082:8082 "${VOLUMES[@]}" "$IMAGE"
}

start_interactive() {
    sudo docker run -it --rm --name "$CONTAINER_NAME" -p 8082:8082 "${VOLUMES[@]}" "$IMAGE"
}

stop_container() {
    sudo docker stop "$CONTAINER_NAME"
}

restart_container() {
    stop_container
    start_detached
}

run_manage() {
    # No arguments: apply the pending migrations (creates the database if it doesn't exist).
    if [ $# -eq 0 ]; then
        set -- migrate
    fi
    # Separate one-off container on the same volumes; --entrypoint replaces whatever the image runs by default.
    sudo docker run --rm -it -w "$APP_DIR" "${VOLUMES[@]}" --entrypoint python "$IMAGE" src/manage.py "$@"
}

case "$1" in
    -it)
        start_interactive
        ;;
    -s)
        stop_container
        ;;
    -r)
        restart_container
        ;;
    -m)
        shift
        run_manage "$@"
        ;;
    *)
        start_detached
        ;;
esac