# Windows Install

Help is never guaranteed but you will have more success in getting help if you have firstly followed this guide:

## Prep

This is the only way I know of getting it working. If you would rather use something like `cygwin`, `WSL`, or `WSL2` you are on your own.

1. Install `choco` using powershell

    ```powershell
    Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    ```

2. Then install [msys2](https://www.msys2.org/) and ConEmu

    ```powershell
    choco install msys2 conemu
    ```

3. Update `msys2`

    ```bash
    pacman -Syu
    ```

4. Install build tools, mpv, fish, and python

    ```bash
    pacman -S mingw-w64-x86_64-mpv mingw-w64-x86_64-youtube-dl make automake python-pip python-wheel fish
    ```

    Optional: xklb[full] deps:

    ```bash
    choco install exiftool
    pacman -S mingw-w64-x86_64-rust
    ```

5. **Configure ConEmu to use fish shell** in msys2

    https://superuser.com/questions/1024301/conemu-how-to-call-msys2-as-tab

6. Set the [MSYSTEM](https://www.msys2.org/docs/environments/) environment variable and close and restart your shell

    ```fish
    set -Ux MSYSTEM MINGW64
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
