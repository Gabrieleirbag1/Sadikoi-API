#!/bin/bash

# Manages the "sadikoi-api" Docker container.
#
# Usage:
#   ./server_sadikoi.sh [option]
#
# Options:
#   (no option)       Start the container in detached mode.
#   -it               Start the container in interactive mode.
#   -s                Stop the container.
#   -r                Restart the container.
#   -m [command...]   Run src/manage.py in a one-off container (default command: migrate).
#                     Run it once before the first start: the API doesn't create the database itself.
#                     Examples: ./server_sadikoi.sh -m
#                               ./server_sadikoi.sh -m showmigrations
#                               ./server_sadikoi.sh -m rollback
#
# Port 8082 on the host is mapped to port 8082 in the container.
# Volumes (kept on the host, so they survive the --rm containers):
#   - $HOST_INSTANCE_DIR -> $APP_DIR/instance     (SQLite database)
#   - $HOST_UPLOADS_DIR  -> $APP_DIR/src/uploads  (uploaded profile pictures)
#   - $HOST_SECRETS_DIR/.*.secrets and .firebase-service-account.json -> $APP_DIR/src/ (read-only)
#     The secrets are excluded from the image (.dockerignore): only the files that exist on the host are mounted.
#
# Logs: everything the container prints is appended to one file per day, $LOG_DIR/YYYY-MM-DD.log
# (logs/ next to this script, git-ignored), each line prefixed with its time, until the container stops.
# Which levels are printed is set when building the image:
#   sudo docker build --build-arg DEBUG=true --build-arg INFO=true -t sadikoi-api .
# (defaults: DEBUG=false, INFO=true).

CONTAINER_NAME="sadikoi-api"
IMAGE="sadikoi-api:latest"
# Working directory of the image (where src/ and instance/ live).
APP_DIR="/app"

# Host folders, next to this script by default (override with environment variables).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_INSTANCE_DIR="${HOST_INSTANCE_DIR:-$SCRIPT_DIR/instance}"
HOST_UPLOADS_DIR="${HOST_UPLOADS_DIR:-$SCRIPT_DIR/src/uploads}"
HOST_SECRETS_DIR="${HOST_SECRETS_DIR:-$SCRIPT_DIR/src}"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"

# Created here, not by Docker: Docker would create missing folders owned by root.
mkdir -p "$HOST_INSTANCE_DIR" "$HOST_UPLOADS_DIR" "$HOST_SECRETS_DIR" "$LOG_DIR"

# The API generates SECRET_KEY when it is missing, but inside a --rm container it would be lost
# on every restart (logging everyone out): create it on the host instead.
AUTH_SECRETS="$HOST_SECRETS_DIR/.auth.secrets"
if [ ! -f "$AUTH_SECRETS" ]; then
    (umask 077 && printf 'SECRET_KEY=%s' "$(openssl rand -hex 32)" > "$AUTH_SECRETS")
    echo "Generated $AUTH_SECRETS"
fi

VOLUMES=(
    -v "$HOST_INSTANCE_DIR:$APP_DIR/instance"
    -v "$HOST_UPLOADS_DIR:$APP_DIR/src/uploads"
)

# Mount each secret file that exists (the admin secret stays out: the admin never runs in the container).
for secret in "$HOST_SECRETS_DIR"/.*.secrets "$HOST_SECRETS_DIR/.firebase-service-account.json"; do
    name="$(basename "$secret")"
    [ -f "$secret" ] && [ "$name" != ".admin.secrets" ] || continue
    VOLUMES+=(-v "$secret:$APP_DIR/src/$name:ro")
done

# Reads log lines on stdin and appends each one to the file of the current day ($LOG_DIR/YYYY-MM-DD.log),
# so a new file starts at midnight without restarting anything. --tee also prints the lines on the terminal.
write_daily_logs() {
    local line now
    while IFS= read -r line || [ -n "$line" ]; do
        printf -v now '%(%F %T)T' -1    # bash builtin: no `date` process per line
        printf '%s %s\n' "${now#* }" "$line" >> "$LOG_DIR/${now%% *}.log"
        [ "$1" = "--tee" ] && printf '%s\n' "$line"
    done
}

start_detached() {
    sudo docker run -d --rm --name "$CONTAINER_NAME" -p 8082:8082 "${VOLUMES[@]}" "$IMAGE" || return
    # Copies the container's output into the daily log files in the background; stops by itself with the container.
    # sudo -n: never waits for a password in the background (the run above just asked for it).
    # trap '' HUP: keeps running after the terminal is closed (what nohup did before).
    (trap '' HUP; sudo -n docker logs -f "$CONTAINER_NAME" 2>&1 | write_daily_logs) </dev/null >/dev/null 2>&1 &
    echo "Logs: $LOG_DIR/$(date +%F).log"
}

start_interactive() {
    sudo docker run -it --rm --name "$CONTAINER_NAME" -p 8082:8082 "${VOLUMES[@]}" "$IMAGE" 2>&1 | write_daily_logs --tee
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