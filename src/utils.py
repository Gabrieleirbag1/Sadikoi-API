import os, json

json_path = os.path.join(os.path.dirname(__file__), 'data')
with open(os.path.join(json_path, 'questions.json'), 'r') as f:
    question_pool = json.load(f)

with open(os.path.join(json_path, 'question_themes.json'), 'r') as f:
    question_themes = json.load(f)
