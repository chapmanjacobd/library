import os, re
from typing import List, Optional

from xklb import utils
from xklb.utils import combine, log, safe_unpack

REGEX_SENTENCE_ENDS = re.compile(r";|,|\.|\*|\n|\t")


def munge_book_tags(media, path) -> Optional[dict]:
    try:
        import textract
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
        log.error(f"[{path}] Failed reading file")
        tags = []
    return {**media, "tags": combine(tags)}


munge_book_tags_fast = utils.with_timeout(70)(munge_book_tags)
munge_book_tags_slow = utils.with_timeout(350)(munge_book_tags)


def pop_substring_keys(e, key_substring):
    values = []
    for k in list(e.keys()):
        if key_substring in k:
            values.append(e.pop(k))
    return values


def munge_image_tags(m: dict, e: dict) -> dict:
    chroma_subsample = int((e.pop("File:YCbCrSubSampling", None) or "0").replace(" ", ""))
    if chroma_subsample == 0:
        chroma_subsample = None

    unit_x = safe_unpack(pop_substring_keys(e, "XResolution"))
    unit_y = safe_unpack(pop_substring_keys(e, "YResolution"))
    unit = safe_unpack(pop_substring_keys(e, "ResolutionUnit"))
    if unit == 0:
        unit = None
        unit_x = None if unit_x == 1 else unit_x
        unit_y = None if unit_y == 1 else unit_y

    m = {
        **m,
        "orientation": safe_unpack(
            pop_substring_keys(e, "Orientation"),
        ),
        "width": safe_unpack(
            e.pop("File:ImageWidth", None),
            e.pop("Composite:ImageWidth", None),
            e.pop("EXIF:ImageWidth", None),
            e.pop("EXIF:ExifImageWidth", None),
            e.pop("PNG:ImageWidth", None),
            *pop_substring_keys(e, "ImageWidth"),
        ),
        "height": safe_unpack(
            e.pop("File:ImageHeight", None),
            e.pop("Composite:ImageHeight", None),
            e.pop("EXIF:ImageHeight", None),
            e.pop("EXIF:ExifImageHeight", None),
            e.pop("PNG:ImageHeight", None),
            *pop_substring_keys(e, "ImageHeight"),
        ),
        "chroma_subsample": chroma_subsample,
        "color_depth": safe_unpack(*pop_substring_keys(e, "ColorResolutionDepth")),
        "color_background": safe_unpack(*pop_substring_keys(e, "BackgroundColor")),
        "color_transparent": safe_unpack(*pop_substring_keys(e, "TransparentColor")),
        "longitude": safe_unpack(*pop_substring_keys(e, "GPSLongitude")),
        "latitude": safe_unpack(*pop_substring_keys(e, "GPSLatitude")),
        "unit": unit,
        "unit_x": unit_x,
        "unit_y": unit_y,
        "exiftool_warning": combine(*pop_substring_keys(e, "ExifTool:Warning")),
        "tags": combine(
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
            *pop_substring_keys(e, "Creator"),
            *pop_substring_keys(e, "Software"),
        ),
    }

    for s in (
        "PDF",
        "ObjectName",
        "YCbCrPositioning",
        ":ISO",
        "ExposureProgram",
        "FNumber",
        "SensingMethod",
        "SubjectDistance",
        "Scene",
        "Sharpness",
        "Saturation",
        "Flash",
        "Contrast",
        "MeteringMode",
        "InteropIndex",
        "ExposureCompensation",
        "BrightnessValue",
        "CustomRendered",
        "ComponentsConfiguration",
        "ShutterSpeed",
        "ExposureMode",
        "Aperture",
        "ScaleFactor",
        "LightValue",
        "GPSProcessingMethod",
        "GPSPosition",
        "focalDistance",
        "GPSDOP",
        "FocalLength",
        "FOV",
        "CircleOfConfusion",
        "GPSLatitudeRef",
        "GPSLongitudeRef",
        "Thumbnail",
        "PrintStyle",
        "Angle",
        "Altitude",
        "Displayed",
        "WriterName",
        "ReaderName",
        "Date",
        "History",
        "Version",
        "Compression",
        "Digest",
        "PrintPosition",
        "PrintScale",
        "Copyright",
        "WhiteBalance",
        "WhitePoint",
        "ColorSpace",
        "ColorTransform",
        "ColorComponents",
        "LightSource",
        "Swatch",
        "Profile",
        "XMP:",
        "ByteOrder",
        "Comment",
        "BitsPerSample",
        "BitsPerPixel",
        "Interpretation",
        "EncodingProcess",
        "Megapixels",
        "PixelAspectRatio",
        "ImageSize",
        "PhotoshopFormat",
        "OriginalTransmissionReference",
        "Time",
        "NumSlices",
        "ImageUniqueID",
        "HasRealMergedData",
        "CodedCharacterSet",
        "Flags0",
        "Flags1",
        "Padding",
        "ProgressiveScans",
        "HasColorMap",
        "Ducky:Quality",
        "PhotoshopQuality",
        "SlicesGroupName",
        "SupplementalCategories",
        "Duration",
        "Animation",
        "FrameCount",
    ):
        pop_substring_keys(e, s)

    for k in (
        "File:FileName",
        "File:Directory",
        "File:FileSize",
        "File:MIMEType",
        "File:FilePermissions",
        "File:FileTypeExtension",
        "File:FileType",
        "IPTC:SpecialInstructions",
        "File:Exif",
    ):
        e.pop(k, None)

    if e != {}:
        log.info("Extra data %s", e)

    return m


def extract_image_metadata_chunk(metadata: List[dict]) -> List[dict]:
    try:
        import exiftool
    except ModuleNotFoundError:
        print(
            "exiftool and PyExifTool are required for image database creation: sudo dnf install perl-Image-ExifTool && pip install PyExifTool",
        )
        raise

    chunk_paths = [d["path"] for d in metadata]
    with exiftool.ExifToolHelper() as et:
        exif = et.get_metadata(chunk_paths)

    exif_enriched = []
    for m, e in zip(metadata, exif):
        assert m["path"] == e.pop("SourceFile")

        try:
            m = munge_image_tags(m, e)
        except Exception as e:
            log.error("[%s]: %s", m["path"], e)
            # continue ?
        exif_enriched.append(m)

    return exif_enriched
