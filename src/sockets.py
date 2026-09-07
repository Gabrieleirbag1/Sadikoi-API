import flask.json
from flask_socketio import SocketIO

# Use Flask's JSON module (not the stdlib json module python-socketio defaults to) so
# emit payloads serialize datetimes the same way REST responses already do via jsonify.
socketio = SocketIO(cors_allowed_origins=["http://localhost:4200", "https://sadikoi.missclick.net"], json=flask.json)
