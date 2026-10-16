"""Shared application error contract; safe to import in stdlib-only supervisors."""


class TaskError(Exception):
    def __init__(self, code, message, status=409, details=None):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status
        self.details = details
