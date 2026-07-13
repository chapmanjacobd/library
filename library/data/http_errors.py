from http import HTTPStatus


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
