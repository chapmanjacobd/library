from pathlib import Path


def p(string):
    return str(Path(string))


def filter_query_param(r1, r2):
    if r1 == r2:
        return True

    query1 = dict(r1.query)
    query2 = dict(r2.query)

    for k in ["key", "api_key"]:
        query1.pop(k, None)
        query2.pop(k, None)

    return query1 == query2
