from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def add_to_db(object):
    try:
        db.session.add(object)
        db.session.commit()
        return {"message": "Object added to the database successfully"}
    except Exception as e:
        db.session.rollback()
        return {"message": "An error occurred while adding the object to the database", "error": True}