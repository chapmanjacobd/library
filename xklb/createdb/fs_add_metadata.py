import os, re
from multiprocessing import TimeoutError as mp_TimeoutError
from pathlib import Path
from timeit import default_timer as timer

from xklb.createdb import av
from xklb.files import sample_hash
from xklb.folders import merge_mv
from xklb.mediafiles import process_ffmpeg, process_image
from xklb.utils import consts, file_utils, iterables, nums, objects, path_utils, processes, strings
from xklb.utils.consts import DBType
from xklb.utils.log_utils import log

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
    except Exception as e:
        log.warning(e)
        log.error(f"Failed reading text. {path}")
        tags = []
    return {"tags": strings.combine(tags)}


munge_book_tags_slow = processes.with_timeout(350)(munge_book_tags)
munge_book_tags_fast = processes.with_timeout(70)(munge_book_tags)


def extract_metadata(mp_args, path) -> dict[str, str | int | None] | None:
    try:
        path.encode()
    except UnicodeEncodeError:
        log.error("Could not encode file path as UTF-8. Skipping %s", path)
        return None

    try:
        stat = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        log.exception("OSError: possible disk error; check dmesg. %s", path)
        return None
    except Exception as e:
        log.error(f"%s {path}", e)
        return None

    media = {
        "path": path,
        "size": stat.st_size,
        "type": file_utils.mimetype(path),
        "time_created": int(stat.st_ctime),
        "time_modified": int(stat.st_mtime) or consts.now(),
        "time_downloaded": consts.APPLICATION_START,
        "time_deleted": 0,
    }

    ext = path.rsplit(".", 1)[-1].lower()
    is_scan_all_files = getattr(mp_args, "scan_all_files", False)

    if media["type"] == "directory":
        return None

    if media["size"] == 0 or not Path(path).exists():
        return media

    if objects.is_profile(mp_args, DBType.audio) and (ext in consts.AUDIO_ONLY_EXTENSIONS or is_scan_all_files):
        media = av.munge_av_tags(mp_args, media)
    elif objects.is_profile(mp_args, DBType.video) and (ext in consts.VIDEO_EXTENSIONS or is_scan_all_files):
        media = av.munge_av_tags(mp_args, media)

    if not Path(path).exists():  # av.munge_av_tags might delete if unplayable or corruption exceeds threshold
        return media

    text_exts = consts.TEXTRACT_EXTENSIONS
    if mp_args.ocr:
        text_exts |= consts.OCR_EXTENSIONS
    if mp_args.speech_recognition:
        text_exts |= consts.SPEECH_RECOGNITION_EXTENSIONS
    if objects.is_profile(mp_args, DBType.text) and (ext in text_exts or is_scan_all_files):
        try:
            start = timer()
            if any([mp_args.ocr, mp_args.speech_recognition]):
                media |= munge_book_tags_slow(path)
            else:
                media |= munge_book_tags_fast(path)
        except mp_TimeoutError:
            log.warning(f"Timed out trying to read file. {path}")
        else:
            log.debug(f"{timer()-start} {path}")

    if getattr(mp_args, "hash", False) and media["type"] != "directory" and media["size"] > 0:
        media["hash"] = sample_hash.sample_hash_file(path)

    if getattr(mp_args, "copy", False) and not file_utils.is_file_open(path):
        dest_path = merge_mv.gen_rel_path(path, mp_args.copy, ":")
        if getattr(mp_args, "clean_path", True):
            dest_path = path_utils.clean_path(os.fsencode(dest_path))
        else:
            dest_path = str(dest_path)
        file_utils.copy_file(path, dest_path, simulate=mp_args.simulate)
        path = media["path"] = dest_path

    if getattr(mp_args, "move", False) and not file_utils.is_file_open(path):
        dest_path = merge_mv.gen_rel_path(path, mp_args.move, ":")
        if getattr(mp_args, "clean_path", True):
            dest_path = path_utils.clean_path(os.fsencode(dest_path))
        else:
            dest_path = str(dest_path)
        file_utils.rename_move_file(path, dest_path, simulate=mp_args.simulate)
        path = media["path"] = dest_path

    if getattr(mp_args, "process", False):
        if objects.is_profile(mp_args, DBType.audio) and Path(path).suffix not in [".opus", ".mka"]:
            result = process_ffmpeg.process_path(
                mp_args,
                path,
                split_longer_than=2160 if mp_args.split_longer_than is None and "audiobook" in path.lower() else None,
            )
            if result is None:
                return None
            path = media["path"] = str(result)
        elif objects.is_profile(mp_args, DBType.video) and Path(path).suffix not in [".av1.mkv"]:
            result = process_ffmpeg.process_path(mp_args, path)
            if result is None:
                return None
            path = media["path"] = str(result)
        elif objects.is_profile(mp_args, DBType.image) and Path(path).suffix not in [".avif", ".avifs"]:
            result = process_image.process_path(mp_args, path)
            if result is None:
                return None
            path = media["path"] = str(result)

    return media


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
        log.exception("exifTool failed executing get_metadata %s", metadata)
        return metadata

    exif_enriched = []
    for m, e in zip(metadata, exif, strict=True):
        assert m["path"] == e.pop("SourceFile")

        try:
            m = munge_image_tags(m, e)
        except Exception as e:
            log.error("[%s]: %s", m["path"], e)
            # continue ?
        exif_enriched.append(m)

    return exif_enriched
