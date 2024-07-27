class HTTPTooManyRequests(EnvironmentError):
    pass


class RecoverableError(Exception):
    pass


class UnrecoverableError(Exception):
    pass


def raise_for_status(status_code):
    if status_code == 429:
        raise HTTPTooManyRequests
    elif status_code in (404,):
        raise UnrecoverableError
    elif 400 <= status_code < 500:
        raise RecoverableError
    elif 500 <= status_code < 600:
        raise RecoverableError
