from types import SimpleNamespace
from unittest import mock

from library.files import llm_map


def test_llm_map_does_not_accumulate_image_flags():
    # 4.1: args.llama_args is mutated inside the per-file loop, so --image flags
    # accumulate and every call after the first passes all prior files' images.
    args = SimpleNamespace(
        llama_args=[], image_model="mmproj.gguf", text=None, rename=False, prompt="x", output=None, exe="/tmp/llamafile"
    )
    with (
        mock.patch.object(llm_map, "parse_args", return_value=args),
        mock.patch.object(llm_map, "gen_paths", return_value=["/a/1.jpg", "/a/2.jpg"]),
        mock.patch.object(llm_map, "run_llama_with_prompt", return_value="out"),
    ):
        llm_map.llm_map()

    assert args.llama_args.count("--image") == 1
