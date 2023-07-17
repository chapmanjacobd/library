import vcr
from vcr.record_mode import RecordMode


def filter_query_param(r1, r2):
    if r1 == r2:
        return True

    query1 = dict(r1.query)
    query2 = dict(r2.query)

    for k in ["key", "api_key"]:
        query1.pop(k, None)
        query2.pop(k, None)

    return query1 == query2


dvd = vcr.VCR(cassette_library_dir="tests/cassettes/", record_mode=RecordMode.NEW_EPISODES)
dvd.register_matcher("filter_query", filter_query_param)
dvd.match_on = ["method", "scheme", "host", "port", "path", "filter_query"]
