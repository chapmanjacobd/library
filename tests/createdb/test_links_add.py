import pytest
from tests.utils import connect_db_args
from xklb.lb import library as lb


def test_links_add(temp_db):
    db1 = temp_db()
    lb(
        [
            'links-add',
            db1,
            'https://arxiv.org/list/cs/recent?skip=0&show=25',
            '--page-key=skip',
            '--page-start=0',
            '--page-step=25',
            '--path-include=/pdf/'
            '--max-pages=2',
        ]
    )

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) >= 30
    assert all('/pdf/' in d['path'] for d in media)
