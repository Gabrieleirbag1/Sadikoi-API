import flask.json
from flask_socketio import SocketIO

from config import ALLOWED_ORIGINS

# Use Flask's JSON module (not the stdlib json module python-socketio defaults to) so
# emit payloads serialize datetimes the same way REST responses already do via jsonify.
socketio = SocketIO(cors_allowed_origins=ALLOWED_ORIGINS, json=flask.json)


def user_room(user_id: int | str) -> str:
    """The room of one user: each of their connections joins it on connect.

    :param user_id: The user.
    :return: The room name.
    :rtype: str
    """
    return f"user-{user_id}"
