import re, sys
from typing import List, Union

from xklb import utils
from xklb.utils import combine, log, safe_unpack

try:
    import textract as _textract
except ModuleNotFoundError:
    _textract = None
try:
    import exiftool as _exiftool
except ModuleNotFoundError:
    _exiftool = None


REGEX_SENTENCE_ENDS = re.compile(r";|,|\.|\*|\n|\t")


def munge_book_tags(media, f) -> Union[dict, None]:
    if _textract is None:
        raise ModuleNotFoundError(
            "textract is required for text database creation: pip install textract; sudo dnf install libxml2-devel libxslt-devel antiword unrtf poppler-utils tesseract sox-plugins-nonfree sox libjpeg-devel swig"
        )
    try:
        tags = _textract.process(f)
        tags = REGEX_SENTENCE_ENDS.split(tags.decode())
    except Exception as e:
        log.warning(e)
        print(f"[{f}] Failed reading file", file=sys.stderr)
        tags = []
    return {**media, "tags": combine(tags)}


munge_book_tags_fast = utils.with_timeout(70)(munge_book_tags)
munge_book_tags_slow = utils.with_timeout(350)(munge_book_tags)


def munge_image_tags(m: dict, e: dict) -> dict:
    chroma_subsample = int((e.pop("File:YCbCrSubSampling", None) or "0").replace(" ", ""))
    if chroma_subsample == 0:
        chroma_subsample = None

    unit_x = safe_unpack([e.pop(k) for k in list(e.keys()) if "XResolution" in k])
    unit_y = safe_unpack([e.pop(k) for k in list(e.keys()) if "YResolution" in k])
    unit = safe_unpack([e.pop(k) for k in list(e.keys()) if "ResolutionUnit" in k])
    if unit == 0:
        unit = None
        unit_x = None if unit_x == 1 else unit_x
        unit_y = None if unit_y == 1 else unit_y

    m = {
        **m,
        "orientation": safe_unpack(
            [e.pop(k) for k in list(e.keys()) if "Orientation" in k],
        ),
        "width": safe_unpack(
            e.pop("File:ImageWidth", None),
            e.pop("Composite:ImageWidth", None),
            e.pop("EXIF:ImageWidth", None),
            e.pop("EXIF:ExifImageWidth", None),
            e.pop("PNG:ImageWidth", None),
            *[e.pop(k) for k in list(e.keys()) if "ImageWidth" in k],
        ),
        "height": safe_unpack(
            e.pop("File:ImageHeight", None),
            e.pop("Composite:ImageHeight", None),
            e.pop("EXIF:ImageHeight", None),
            e.pop("EXIF:ExifImageHeight", None),
            e.pop("PNG:ImageHeight", None),
            *[e.pop(k) for k in list(e.keys()) if "ImageHeight" in k],
        ),
        "chroma_subsample": chroma_subsample,
        "color_depth": safe_unpack(*[e.pop(k) for k in list(e.keys()) if "ColorResolutionDepth" in k]),
        "color_background": safe_unpack(*[e.pop(k) for k in list(e.keys()) if "BackgroundColor" in k]),
        "color_transparent": safe_unpack(*[e.pop(k) for k in list(e.keys()) if "TransparentColor" in k]),
        "longitude": safe_unpack(*[e.pop(k) for k in list(e.keys()) if "GPSLongitude" in k]),
        "latitude": safe_unpack(*[e.pop(k) for k in list(e.keys()) if "GPSLatitude" in k]),
        "unit": unit,
        "unit_x": unit_x,
        "unit_y": unit_y,
        "exiftool_warning": combine(*[e.pop(k) for k in list(e.keys()) if "ExifTool:Warning" in k]),
        "tags": combine(
            *[e.pop(k) for k in list(e.keys()) if "Headline" in k],
            *[e.pop(k) for k in list(e.keys()) if "Title" in k],
            *[e.pop(k) for k in list(e.keys()) if "ImageDescription" in k],
            *[e.pop(k) for k in list(e.keys()) if "Caption" in k],
            *[e.pop(k) for k in list(e.keys()) if "Artist" in k],
            *[e.pop(k) for k in list(e.keys()) if "By-line" in k],
            *[e.pop(k) for k in list(e.keys()) if "Credit" in k],
            *[e.pop(k) for k in list(e.keys()) if "DocumentNotes" in k],
            *[e.pop(k) for k in list(e.keys()) if "URL_List" in k],
            *[e.pop(k) for k in list(e.keys()) if "Keywords" in k],
            *[e.pop(k) for k in list(e.keys()) if "Make" in k],
            *[e.pop(k) for k in list(e.keys()) if "Model" in k],
            *[e.pop(k) for k in list(e.keys()) if "Creator" in k],
            *[e.pop(k) for k in list(e.keys()) if "Software" in k],
        ),
    }

    for s in [
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
    ]:
        [e.pop(k) for k in list(e.keys()) if s in k]

    for k in [
        "File:FileName",
        "File:Directory",
        "File:FileSize",
        "File:MIMEType",
        "File:FilePermissions",
        "File:FileTypeExtension",
        "File:FileType",
        "IPTC:SpecialInstructions",
        "File:Exif",
    ]:
        e.pop(k, None)

    if e != {}:
        log.info("Extra data %s", e)

    return m


def extract_image_metadata_chunk(metadata: List[dict], chunk_paths: List[str]) -> List[dict]:
    if _exiftool is None:
        raise ModuleNotFoundError(
            "exiftool and PyExifTool are required for image database creation: sudo dnf install perl-Image-ExifTool && pip install PyExifTool"
        )

    with _exiftool.ExifToolHelper() as et:
        exif = et.get_metadata(chunk_paths)

    exif_enriched = []
    for m, e in zip(metadata, exif):
        assert m["path"] == e.pop("SourceFile")

        try:
            m = munge_image_tags(m, e)
        except Exception as e:
            # raise e
            log.error("[%s]: %s", m["path"], e)
            pass

        exif_enriched.append(m)

    return metadata
