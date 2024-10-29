import re

environment_error = re.compile(
    "|".join(
        r""".*no space left
.*ENOSPC
.*disk full
.*file system error
.*read-only
.*read only
.*permission denied
.*file name too long""".splitlines(),
    )
)

unsupported_error = re.compile(
    "|".join(
        r""".*Unsupported archive format.
.*unknown error
.*password
.*unknown
.*not implemented
.*unsupported""".splitlines(),
    ),
    flags=re.IGNORECASE,
)

file_error = re.compile(
    "|".join(
        r""".*Error on decrunching
.*Wrong checksum
.*Attempted to read more data than was available
.*Error on unpacking
.*Archive is corrupted""".splitlines(),
    ),
    flags=re.IGNORECASE,
)
