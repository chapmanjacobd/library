from xklb.lb import library as lb


def test_stdin(mock_stdin, capsys):
    with mock_stdin(
        '{"or Place of Birth":"Bangladesh","Foreign State of Chargeability Visa Class":"F43","Issuances":"2"}'
    ):
        lb(["json-keys-rename", "--country", "place of birth", "--visa-type", "visa class", "--count", "issuances"])
    captured = capsys.readouterr().out
    assert captured == '{"country": "Bangladesh", "visa_type": "F43", "count": "2"}'
