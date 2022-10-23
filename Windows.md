# Windows Install

Install `choco` using powershell

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

## Powershell (recommended)

Install dependencies

```powershell
choco install mpv ffmpeg
```

Optional: xklb[full] deps:

```powershell
choco install exiftool rust
```

## Install

Install xklb and enjoy!

```fish
pip install xklb
lb
xk media library

local media subcommands:
  fsadd [extract, xr]                Create a local media database; Add folders
  listen [lt]                        Listen to local media
  watch [wt]                         Watch local media
```


## Alternative Environment: msys2

`cygwin`, `WSL`, or `WSL2` is not recommended.

1. Install [msys2](https://www.msys2.org/) and ConEmu

    ```powershell
    choco install msys2 conemu
    ```

2. Update `msys2`

    ```bash
    pacman -Syu
    ```

3. Install build tools, mpv, fish, and python

    ```bash
    pacman -S mingw-w64-x86_64-mpv mingw-w64-x86_64-youtube-dl make automake python-pip python-wheel fish
    ```

    Optional: xklb[full] deps:

    ```bash
    choco install exiftool
    pacman -S mingw-w64-x86_64-rust
    ```

4. **Configure ConEmu to use fish shell** in msys2

    https://superuser.com/questions/1024301/conemu-how-to-call-msys2-as-tab

5. Set the [MSYSTEM](https://www.msys2.org/docs/environments/) environment variable and close and restart your shell

    ```fish
    set -Ux MSYSTEM MINGW64
    ```
