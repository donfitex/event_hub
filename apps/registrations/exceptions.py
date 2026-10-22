class RegistrationError(Exception):
    """A business-rule failure with a machine-readable code and HTTP status."""

    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code