from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def add_to_db(object):
    try:
        db.session.add(object)
        db.session.commit()
        return {"message": "Object added to the database successfully"}
    except Exception:
        db.session.rollback()
        return {"message": "An error occurred while adding the object to the database", "error": True}
    
def delete_from_db(object):
    try:
        db.session.delete(object)
        db.session.commit()
        return {"message": "Object deleted from the database successfully"}
    except Exception:
        db.session.rollback()
        return {"message": "An error occurred while deleting the object from the database", "error": True}
    
def update_from_db():
    try:
        db.session.commit()
        return {"message": "Object updated in the database successfully"}
    except Exception:
        db.session.rollback()
        return {"message": "An error occurred while updating the object in the database", "error": True}