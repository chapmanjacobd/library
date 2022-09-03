# Windows Install

Help is never guaranteed but you will have more success in getting help if you have firstly followed this guide:

## Prep

This is the only way I know of getting it working. If you would rather use something like `cygwin`, `WSL`, or `WSL2` you are on your own.

1. Install `choco` using powershell

2. Then install [msys2](https://www.msys2.org/)

    ```powershell
    choco install msys2
    ```

3. Update `msys2`

    ```bash
    pacman -Syu
    ```

4. Install build tools, mpv, fish, and python

    ```bash
    pacman -S mingw-w64-x86_64-mpv mingw-w64-x86_64-youtube-dl make automake python-pip python-wheel fish
    ```

5. Install ConEmu and **configure it to use fish shell** in msys2

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
  subtitle [sub]                     Find subtitles for local media
  listen [lt]                        Listen to local media
  watch [wt]                         Watch local media
  filesystem [fs]                    Browse files

online media subcommands:
  tubeadd [ta]                       Create a tube database; Add playlists
  tubeupdate [tu]                    Update your saved playlists
  tubelist [playlist, playlists]     List added playlists
  tubewatch [tw, tube, entries]      Watch the tube
  tubelisten [tl]                    Listen to the tube

browser tab subcommands:
  tabsadd                            Create a tabs database; Add URLs
  tabs [tabswatch, tb]               Open your tabs for the day
```