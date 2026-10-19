from library.__main__ import library as lb
from tests.utils import connect_db_args


def test_substack_add(temp_db):
    db1 = temp_db()
    lb(["substack", db1, "https://www.astralcodexten.com/p/contra-kriss-on-nerds-and-hipsters"])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) == 1
    assert media[0]["title"] == "Contra Kriss On Nerds And Hipsters"
    text = media[0]["text"]
    assert "Hipsters, he says, are an information sorting algorithm" in text
    assert "was enough cover to make it still seem interesting and impressive" in text
