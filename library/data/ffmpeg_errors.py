import re

environment_error = re.compile(
    "|".join(
        r""".*No space left on device
.*Transport endpoint is not connected
.*File name too long""".splitlines(),
    )
)


ignore_error = re.compile(
    "|".join(
        r""".*warning
.*deprecated""".splitlines(),
    )
)

unsupported_subtitle_error = re.compile(
    "|".join(
        r""".*Subtitle codec.*not supported""".splitlines(),
    ),
    flags=re.IGNORECASE,
)

unsupported_error = re.compile(
    "|".join(
        r""".*at least one.* received no packets
.*does not contain any stream
.*Subtitle encoding currently only possible from text to text or bitmap to bitmap
.*not implemented
.*Unsupported codec""".splitlines(),
    ),
    flags=re.IGNORECASE,
)

file_error = re.compile(
    "|".join(
        r""".*detected.*low score
.*no decoder found for: none
.*Error initializing filters""".splitlines(),
    ),
    flags=re.IGNORECASE,
)
