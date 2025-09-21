from http import HTTPStatus


# TODO: remove after min py3.11
def _is_informational(self):
    return 100 <= self.value <= 199


def _is_success(self):
    return 200 <= self.value <= 299


def _is_redirection(self):
    return 300 <= self.value <= 399


def _is_client_error(self):
    return 400 <= self.value <= 499


def _is_server_error(self):
    return 500 <= self.value <= 599


for name, func in {
    "is_informational": _is_informational,
    "is_success": _is_success,
    "is_redirection": _is_redirection,
    "is_client_error": _is_client_error,
    "is_server_error": _is_server_error,
}.items():
    if not hasattr(HTTPStatus, name):
        setattr(HTTPStatus, name, property(func))


class HTTPTooManyRequests(EnvironmentError):
    pass


class RecoverableError(RuntimeError):
    pass


class UnrecoverableError(RuntimeError):
    pass


def raise_for_status(status_code):
    code = HTTPStatus(status_code)
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise HTTPTooManyRequests

    elif status_code == HTTPStatus.NOT_FOUND:
        raise UnrecoverableError("HTTP404: HTTPNotFound")

    elif code.is_client_error:
        msg = f"HTTP{status_code}"
        raise RecoverableError(msg)

    elif code.is_server_error:
        msg = f"HTTP{status_code}"
        raise RecoverableError(msg)
