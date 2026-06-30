import datetime

from flask_login import current_user
from auth import get_user_object
from models import UserModel, BugReportModel, SuggestionModel
from db import add_to_db

def is_user_spamming(user: UserModel, feedback: BugReportModel | SuggestionModel, time_threshold: int = 60) -> bool:
    """Check if the user is submitting bug reports or suggestions too frequently."""
    last_report = (
        feedback.query
        .filter_by(user_id=user.id)
        .order_by(feedback.timestamp.desc())
        .first()
    )

    if last_report is None:
        return False

    time_since_last_report = (
        datetime.datetime.now(datetime.timezone.utc) - last_report.timestamp.replace(tzinfo=datetime.timezone.utc)
    ).total_seconds()

    return time_since_last_report < time_threshold

def create_bug_report(request):
    """Create a new bug report."""
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    if is_user_spamming(user, BugReportModel):
        return {"success": False, "message": "You are submitting bug reports too frequently. Please wait before submitting another."}, 429
    
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

def create_suggestion(request):
    """Create a new suggestion."""
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    if is_user_spamming(user, SuggestionModel, 20):
        return {"success": False, "message": "You are submitting suggestions too frequently. Please wait before submitting another."}, 429
    
    theme = request.json.get("theme")
    question = request.json.get("question")

    if not theme or not question:
        return {"success": False, "message": "Theme and question are required"}, 400
    
    suggestion = SuggestionModel(user_id=user.id, theme=theme, question=question)
    result = add_to_db(suggestion)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "Suggestion created successfully"}, 201