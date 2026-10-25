from apps.common.exceptions import DomainError


class RegistrationError(DomainError):
    """Registration rule failure. Same signature: RegistrationError(code, message, status_code)."""