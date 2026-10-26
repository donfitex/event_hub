from contextlib import contextmanager

import pytest

from apps.registrations.exceptions import RegistrationError


@contextmanager
def expect_error(code, status=409):
    """Assert that the block raises RegistrationError with this code and HTTP status."""
    with pytest.raises(RegistrationError) as exc_info:
        yield
    assert exc_info.value.code == code
    assert exc_info.value.status_code == status