from flask import Flask
from db import db
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.secret_key = os.urandom(24) 

db.init_app(app)

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(port=8082, debug=True)