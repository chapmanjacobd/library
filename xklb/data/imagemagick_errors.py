import re

environment_error = re.compile(
    "|".join(
        r""".*No space left on device
.*unable to write
.*File name too long
.*unable to open image""".splitlines(),
    )
)


ignore_error = re.compile(
    "|".join(
        r""".*@ warning/""".splitlines(),
    )
)

unsupported_error = re.compile(
    "|".join(
        r""".*unsupported
.* not supported
.* password
.* no images defined
.* bad magic number
.*can not handle
.* count
.* exceeded
.* allocation failed
.*no decode delegate for this image format""".splitlines(),
    ),
    flags=re.IGNORECASE,
)

image_error = re.compile(
    "|".join(
        r""".*insufficient image data in file
.*Not enough data
.*corrupt
.*Read Exception
.*read error at
.*too large
.*Sanity check.* failed
.*size exceeds expected dimensions
.*Nonstandard
.*decompress
.*improper image header
.*Not .* starts with
.*IO error during reading
.*unable to decode image file""".splitlines(),
    ),
    flags=re.IGNORECASE,
)
