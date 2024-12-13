class HTTPTooManyRequests(EnvironmentError):
    pass


class RecoverableError(RuntimeError):
    pass


class UnrecoverableError(RuntimeError):
    pass


def raise_for_status(status_code):
    if status_code == 429:
        raise HTTPTooManyRequests
    elif status_code in (404,):
        raise UnrecoverableError("HTTP404: HTTPNotFound")
    elif 400 <= status_code < 500:
        msg = f"HTTP{status_code}"
        raise RecoverableError(msg)
    elif 500 <= status_code < 600:
        msg = f"HTTP{status_code}"
        raise RecoverableError(msg)
