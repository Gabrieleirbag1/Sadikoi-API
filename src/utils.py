import os, json

json_path = os.path.join(os.path.dirname(__file__), 'data')
with open(os.path.join(json_path, 'questions.json'), 'r') as f:
    question_pool = json.load(f)

with open(os.path.join(json_path, 'question_themes.json'), 'r') as f:
    question_themes = json.load(f)

# Languages the questions and emails exist in; anything else falls back to the first one.
SUPPORTED_LANGUAGES = ('en', 'fr')


def normalize_language(value, default: str = SUPPORTED_LANGUAGES[0]) -> str:
    """"fr-FR" -> "fr"; an unsupported or missing language -> default.

    :param value: The language sent by the app or Google (e.g. "en-US").
    :param str default: The language to use when value is not supported.

    :return: A supported language.
    :rtype: str
    """
    primary = str(value or '').split('-')[0].split('_')[0].lower()
    return primary if primary in SUPPORTED_LANGUAGES else default
