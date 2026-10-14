"""Errors shared by social services and their HTTP boundary."""


class SocialError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status
