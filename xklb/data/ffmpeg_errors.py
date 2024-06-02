import re

environment_error = re.compile(
    "|".join(
        r""".*No space left on device
.*File name too long""".splitlines(),
    )
)


ignore_error = re.compile(
    "|".join(
        r""".*warning
.*deprecated""".splitlines(),
    )
)

unsupported_error = re.compile(
    "|".join(
        r""".*at least one.* received no packets
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
