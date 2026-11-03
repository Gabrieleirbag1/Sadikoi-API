class ValueTooLongException(Exception):
    """Exception raised when a value exceeds the allowed length."""
    pass

class InvalidChoiceException(ValueError):
    """Exception raised when a value is not one of the allowed choices."""
    pass
