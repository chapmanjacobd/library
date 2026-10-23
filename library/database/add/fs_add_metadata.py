import argparse, os, re
from multiprocessing import TimeoutError as mp_TimeoutError
from pathlib import Path
from timeit import default_timer as timer

from library.database.add import av
from library.file import sample_hash
from library.shrink import process_ffmpeg, process_image
from library.utils import arggroups, consts, file_utils, iterables, nums, objects, processes, shell_utils, strings
from library.utils.consts import DBType
from library.utils.log_utils import log

REGEX_SENTENCE_ENDS = re.compile(r";|,|\.|\*|\n|\t")


def pop_substring_keys(e, key_substring):
    return [e.pop(k) for k in list(e.keys()) if key_substring in k]


def munge_book_tags(path) -> dict:
    try:
        import textract  # type: ignore
    except ModuleNotFoundError:
        print(
            "textract is required for text database creation: pip install textract; sudo dnf install libxml2-devel libxslt-devel antiword unrtf poppler-utils tesseract sox-plugins-nonfree sox libjpeg-devel swig",
        )
        raise
    try:
        tags = textract.process(path, language=os.getenv("TESSERACT_LANGUAGE"))
        tags = REGEX_SENTENCE_ENDS.split(tags.decode())
    except Exception as excinfo:
        log.warning(excinfo)
        log.error(f"Failed reading text. {path}")
        tags = []
    return {"tags": strings.combine(tags)}


munge_book_tags_slow = processes.with_timeout(350)(munge_book_tags)
munge_book_tags_fast = processes.with_timeout(70)(munge_book_tags)


def _get_file_metadata(path):
    try:
        path.encode()
    except UnicodeEncodeError:
        log.error("Could not encode file path as UTF-8. Skipping %s", path)
        return None

    try:
        stat = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as excinfo:
        errmsg = str(excinfo)
        if path not in errmsg:
            errmsg = f"{path} {errmsg}"
        log.error("%s: %s", type(excinfo).__name__, errmsg)
        return None
    except Exception as excinfo:
        log.error(f"%s {path}", excinfo)
        return None

    try:
        mimetype = file_utils.detect_mimetype(path)
    except TimeoutError:
        mimetype = None

    return {
        "path": path,
        "size": stat.st_size,
        "type": mimetype,
        "time_created": int(stat.st_ctime),
        "time_modified": int(stat.st_mtime) or consts.now(),
        "time_downloaded": consts.APPLICATION_START,
        "time_deleted": 0,
    }


def _extract_av_metadata(mp_args, m, ext, is_scan_all_files):
    is_audio_scan = objects.is_profile(mp_args, DBType.audio) and (
        ext in consts.AUDIO_ONLY_EXTENSIONS or is_scan_all_files
    )
    is_video_scan = objects.is_profile(mp_args, DBType.video) and (
        ext in consts.VIDEO_EXTENSIONS or is_scan_all_files
    )
    if is_audio_scan or is_video_scan:
        m = av.munge_av_tags(mp_args, m)
    return m


def _extract_text_metadata(mp_args, m, path, ext, is_scan_all_files):
    if not (
        objects.is_profile(mp_args, DBType.text)
        and (ext in arggroups.text_extensions(mp_args) or is_scan_all_files)
    ):
        return m
    if not arggroups.text_profile_available():
        log.debug("textract is not installed; skipping text extraction for %s", path)
        return m
    try:
        start = timer()
        if any([mp_args.ocr, mp_args.speech_recognition]):
            m |= munge_book_tags_slow(path)
        else:
            m |= munge_book_tags_fast(path)
    except (mp_TimeoutError, TimeoutError):
        log.warning(f"Timed out trying to read file. {path}")
    else:
        log.debug(f"{timer() - start} {path}")
    return m


def _apply_file_operations(mp_args, m, path):
    if getattr(mp_args, "hash", False) and m["type"] != "directory" and m["size"] > 0:
        m["hash"] = sample_hash.sample_hash_file(path)
    if getattr(mp_args, "copy", False) and not file_utils.is_file_open(path):
        path = m["path"] = shell_utils.copy(mp_args, path, str(mp_args.copy))
    if getattr(mp_args, "move", False) and not file_utils.is_file_open(path):
        m["path"] = shell_utils.rel_move(mp_args, path, str(mp_args.move))
    return m


def _process_media(mp_args, m, path):
    if not getattr(mp_args, "process", False):
        return m

    process_ext = Path(path).suffix.lstrip(".").lower()
    handlers = [
        (
            objects.is_profile(mp_args, DBType.audio)
            and process_ext in consts.AUDIO_ONLY_EXTENSIONS
            and Path(path).suffix not in [".opus", ".mka"],
            lambda: process_ffmpeg.process_path(
                mp_args,
                path,
                split_longer_than=2160 if mp_args.split_longer_than is None and "audiobook" in path.lower() else None,
            ),
        ),
        (
            objects.is_profile(mp_args, DBType.video)
            and process_ext in consts.VIDEO_EXTENSIONS
            and Path(path).suffix != ".av1.mkv",
            lambda: process_ffmpeg.process_path(mp_args, path),
        ),
        (
            objects.is_profile(mp_args, DBType.image)
            and process_ext in consts.IMAGE_EXTENSIONS
            and Path(path).suffix not in [".avif", ".avifs"],
            lambda: process_image.process_path(mp_args, path),
        ),
    ]
    for should_process, process in handlers:
        if should_process:
            result = process()
            if result is None:
                return None
            if isinstance(result, list):
                processed_args = argparse.Namespace(**(vars(mp_args) | {"process": False}))
                return [
                    metadata
                    for output_path in result
                    if (metadata := extract_metadata(processed_args, output_path))
                ]
            m["path"] = str(result)
            break
    return m


def extract_metadata(mp_args, path) -> dict[str, str | int | None] | list[dict[str, str | int | None]] | None:
    m = _get_file_metadata(path)
    if m is None:
        return None

    ext = path.rsplit(".", 1)[-1].lower()
    is_scan_all_files = getattr(mp_args, "scan_all_files", False)

    if m["type"] == "directory":
        return None

    if m["size"] == 0 or not Path(path).exists():
        return m

    m = _extract_av_metadata(mp_args, m, ext, is_scan_all_files)

    if not Path(path).exists():  # av.munge_av_tags might delete if unplayable or corruption exceeds threshold
        return m

    m = _extract_text_metadata(mp_args, m, path, ext, is_scan_all_files)
    m = _apply_file_operations(mp_args, m, path)
    return _process_media(mp_args, m, m["path"])


def munge_image_tags(m: dict, e: dict) -> dict:
    chroma_subsample = nums.safe_int(
        iterables.safe_unpack(
            e.pop("File:YCbCrSubSampling", None),
            *pop_substring_keys(e, "YCbCrSubSampling"),
        )
    )
    if chroma_subsample == 0:
        chroma_subsample = None

    unit_x = iterables.safe_unpack(
        *pop_substring_keys(e, "XResolution"),
    )
    unit_y = iterables.safe_unpack(
        *pop_substring_keys(e, "YResolution"),
    )
    unit = iterables.safe_unpack(
        *pop_substring_keys(e, "ResolutionUnit"),
    )
    if unit == 0:
        unit = None
        unit_x = None if unit_x == 1 else unit_x
        unit_y = None if unit_y == 1 else unit_y

    m = {
        **m,
        "orientation": iterables.safe_unpack(
            *pop_substring_keys(e, "Orientation"),
        ),
        "width": iterables.safe_unpack(
            e.pop("File:ImageWidth", None),
            e.pop("Composite:ImageWidth", None),
            e.pop("EXIF:ImageWidth", None),
            e.pop("EXIF:ExifImageWidth", None),
            e.pop("PNG:ImageWidth", None),
            *pop_substring_keys(e, "ImageWidth"),
        ),
        "height": iterables.safe_unpack(
            e.pop("File:ImageHeight", None),
            e.pop("Composite:ImageHeight", None),
            e.pop("EXIF:ImageHeight", None),
            e.pop("EXIF:ExifImageHeight", None),
            e.pop("PNG:ImageHeight", None),
            *pop_substring_keys(e, "ImageHeight"),
        ),
        "chroma_subsample": chroma_subsample,
        "color_depth": iterables.safe_unpack(
            *pop_substring_keys(e, "ColorResolutionDepth"),
        ),
        "color_background": iterables.safe_unpack(
            *pop_substring_keys(e, "BackgroundColor"),
        ),
        "color_transparent": iterables.safe_unpack(
            *pop_substring_keys(e, "TransparentColor"),
        ),
        "longitude": iterables.safe_unpack(
            e.pop("Composite:GPSLongitude", None),
            *pop_substring_keys(e, "GPSLongitude"),
        ),
        "latitude": iterables.safe_unpack(
            e.pop("Composite:GPSLatitude", None),
            *pop_substring_keys(e, "GPSLatitude"),
        ),
        "focal_length": iterables.safe_unpack(
            e.pop("Composite:Lens", None),
            *pop_substring_keys(e, "Lens35efl"),
        ),
        "unit": unit,
        "unit_x": unit_x,
        "unit_y": unit_y,
        "exiftool_warning": strings.combine(*pop_substring_keys(e, "ExifTool:Warning")),
        "tags": strings.combine(
            *pop_substring_keys(e, "Headline"),
            *pop_substring_keys(e, "Title"),
            *pop_substring_keys(e, "ImageDescription"),
            *pop_substring_keys(e, "Caption"),
            *pop_substring_keys(e, "Artist"),
            *pop_substring_keys(e, "By-line"),
            *pop_substring_keys(e, "Credit"),
            *pop_substring_keys(e, "DocumentNotes"),
            *pop_substring_keys(e, "URL_List"),
            *pop_substring_keys(e, "Keywords"),
            *pop_substring_keys(e, "Make"),
            *pop_substring_keys(e, "Model"),
            *pop_substring_keys(e, "LensID"),
            *pop_substring_keys(e, "Creator"),
            *pop_substring_keys(e, "Software"),
        ),
    }

    return m


def extract_image_metadata_chunk(metadata: list[dict]) -> list[dict]:
    try:
        import exiftool
    except ModuleNotFoundError:
        print(
            "exiftool and PyExifTool are required for image database creation: sudo dnf install perl-Image-ExifTool && pip install PyExifTool",
        )
        raise

    chunk_paths = [d["path"] for d in metadata]
    try:
        with exiftool.ExifToolHelper() as et:
            exif = et.get_metadata(chunk_paths)
    except exiftool.exceptions.ExifToolExecuteError:
        log.error(
            "exifTool failed executing get_metadata on %s items starting %s ending %s",
            len(metadata),
            metadata[0]["path"],
            metadata[-1]["path"],
        )
        return metadata

    exif_enriched = []
    for metadata_entry, exif_entry in zip(metadata, exif, strict=True):
        assert metadata_entry["path"] == exif_entry.pop("SourceFile")

        enriched_entry = metadata_entry
        try:
            enriched_entry = munge_image_tags(metadata_entry, exif_entry)
        except Exception as excinfo:
            log.error("[%s]: %s", metadata_entry["path"], excinfo)
            # continue ?
        exif_enriched.append(enriched_entry)

    return exif_enriched
