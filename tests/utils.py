import vcr

dvd = vcr.VCR(cassette_library_dir="tests/cassettes/", filter_query_parameters=["key"])
# dvd.match_on = ["method", "scheme", "host", "port", "path"]
