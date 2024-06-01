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
        r""".*at least one.* received no packets""".splitlines(),
    ),
    flags=re.IGNORECASE,
)

file_error = re.compile(
    "|".join(
        r""".*corrupted""".splitlines(),
    ),
    flags=re.IGNORECASE,
)
