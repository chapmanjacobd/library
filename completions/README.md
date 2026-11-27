# Shell completions for `library` / `lb`

The files in this directory complete nested commands, aliases, options, and
common option values for the `library` and `lb` executables.

| Shell | File | Install |
| --- | --- | --- |
| Bash | `lb.bash` | Copy to a bash-completion directory (for example `~/.local/share/bash-completion/completions/lb`), or `source completions/lb.bash` in `~/.bashrc`. |
| Zsh | `_lb`, `_library` | Copy both files into a directory on `$fpath` (for example `~/.local/share/zsh/site-functions`). |
| Fish | `lb.fish`, `library.fish` | Copy both files into `~/.config/fish/completions/`. |
| PowerShell | `lb.ps1` | Dot-source the file from `$PROFILE`, for example `. ~/completions/lb.ps1`. Requires PowerShell 7 (`-Native` argument completers). |

Fish and zsh can also install directly from the CLI:

```sh
library completions fish > ~/.config/fish/completions/lb.fish
library completions zsh > "${fpath[1]}/_lb"
```

## Regenerate

Regenerate the committed files after changing commands, aliases, or argparse
options:

```sh
library completions bash > completions/lb.bash
library completions zsh > completions/_lb
library completions fish > completions/lb.fish
library completions powershell > completions/lb.ps1
```

`library completions --list` prints the supported shell names.
