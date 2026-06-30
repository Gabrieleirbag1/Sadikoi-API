from flask_login import current_user
from auth import get_user_object
from models import UserModel, BugReportModel
from db import add_to_db

def create_bug_report(request):
    """Create a new bug report."""
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    title = request.json.get("title")
    description = request.json.get("description")
    device_name = request.json.get("device_name", "Unknown Device")

    if not title or not description:
        return {"success": False, "message": "Title and description are required"}, 400
    
    bug_report = BugReportModel(user_id=user.id, title=title, description=description, device_name=device_name)
    result = add_to_db(bug_report)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "Bug report created successfully"}, 201