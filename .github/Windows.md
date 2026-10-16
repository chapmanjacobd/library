# Windows Install

Install `choco` using powershell

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

Install dependencies with choco

```powershell
choco install mpv ffmpeg python fd
```

Then install library and enjoy!

```fish
pip install library
lb
```

Run `lb` to list the available subcommands (grouped by resource) and
`lb <command> -h` for help with any one of them. The common entry points are
`database add filesystem` (scan local media), `play video`, and `play audio`.

Optional: library[deluxe] deps: `choco install exiftool rust`

Torrent metadata support requires the libtorrent-rasterbar Python bindings,
published on PyPI as `libtorrent`. PyPI provides Windows wheels for Python
3.12 and 3.13; use Python 3.13 and install the deluxe extra:

```powershell
py -3.13 -m pip install "library[deluxe]"
```

There is no official Scoop package for the Python bindings.

<details>
  <summary><h3>Alternative environment: msys2</h3></summary>

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

    Optional: library[deluxe] deps:

    ```bash
    choco install exiftool
    pacman -S mingw-w64-x86_64-rust
    ```

4. **Configure ConEmu to use fish shell** in msys2

    https://superuser.com/questions/1024301/conemu-how-to-call-msys2-as-tab

5. Set the [MSYSTEM](https://www.msys2.org/docs/environments/) environment variable and close and restart your shell

    ```fish
    set -Ux MSYSTEM MINGW64
    set -Ux PYTHONUTF8 1
    ```

</details>
