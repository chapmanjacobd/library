from xklb.utils import mv_to_keep_folder


def test_mv_to_keep_folder():
    mv_to_keep_folder("folder/file.opus")
    mv_to_keep_folder("folder/keep/file.opus")
    mv_to_keep_folder("folder/keep/keep/file.opus")
