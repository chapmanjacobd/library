import sys, time, warnings
from pathlib import Path
from urllib.parse import urljoin

from library.mediafiles import media_check
from library.utils import arggroups, argparse_utils, file_utils, path_utils, processes, web


def jav_guru() -> None:
    warnings.warn(
        "This subcommand will likely be removed in future versions--"
        "Unless enough people complain or a generous benefactor appears",
        DeprecationWarning,
        stacklevel=2,
    )

    parser = argparse_utils.ArgumentParser()
    arggroups.selenium(parser)
    arggroups.download(parser)
    parser.add_argument("--small", action="store_true")
    arggroups.debug(parser)

    parser.add_argument("path", help="JAV.GURU URL")
    args = parser.parse_args()
    arggroups.selenium_post(args)

    from selenium.common.exceptions import NoSuchElementException
    from selenium.webdriver.common.by import By

    available_providers = ["TV", "ST"]  # , 'DD', 'JK', 'MD'
    tried_providers = []

    def load_stream(driver):
        for provider in (s for s in available_providers if s not in tried_providers):
            try:
                stream_btn = driver.find_element(By.PARTIAL_LINK_TEXT, f"STREAM {provider}")
                stream_btn.click()
                return provider
            except NoSuchElementException:
                tried_providers.append(provider)

        raise RuntimeError("No video stream found")

    def process_url(line):
        url = line.rstrip("\n")
        if url in ["", '""', "\n"]:
            return None

        web.load_selenium(args)
        try:
            args.driver.get(url)
            args.driver.implicitly_wait(5)

            title = args.driver.find_element(By.CSS_SELECTOR, "h1.titl").text.replace("/", "-").replace("\\", "-")
            target_dir = Path.cwd() / "javguru"
            target_dir.mkdir(exist_ok=True)
            output_path = path_utils.clean_path(bytes(target_dir / f"{title}.mp4"), max_name_len=255)
            local_probe = None
            if Path(output_path).exists():
                try:
                    local_probe = processes.FFProbe(output_path)
                    assert local_probe.has_audio
                    assert local_probe.has_video
                except Exception:
                    Path(output_path).unlink()

            provider = load_stream(args.driver)

            time.sleep(2)
            iframe = args.driver.find_element(By.CSS_SELECTOR, "iframe[src^='https://jav.guru']")
            args.driver.switch_to.frame(iframe)
            time.sleep(1)
            args.driver.execute_script("start_player()")

            time.sleep(3)
            iframe = args.driver.find_element(By.CSS_SELECTOR, "iframe[src^='https://jav.guru']")  # nested iframe
            args.driver.switch_to.frame(iframe)

            if provider == "TV":
                # args.driver.execute_script("play()")
                master_playlist_url = args.driver.execute_script("return urlPlay;")

            elif provider == "ST":
                try:
                    video_div = args.driver.find_element(By.CSS_SELECTOR, "div.play-overlay")
                except Exception:
                    video_div = args.driver.find_element(By.CSS_SELECTOR, "div.plyr__video-wrapper")
                video_div.click()
                video_element = args.driver.find_element(By.TAG_NAME, "video")
                video_src = video_element.get_attribute("src")
                master_playlist_url = urljoin("https:", video_src)

        finally:
            web.quit_selenium(args)

        try:
            remote_probe = processes.FFProbe(
                master_playlist_url,  # type: ignore
                "-headers",
                "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
                "-headers",
                "Referer: https://emturbovid.com/",
            )

            video_streams = list(remote_probe.video_streams)
            if args.small:
                video_streams = [s for s in video_streams if s["height"] <= 720]
            video_streams.sort(key=lambda s: s["height"], reverse=True)
            video_index = video_streams[0]["index"]

            audio_streams = remote_probe.audio_streams
            audio_streams.sort(key=lambda s: (s["tags"].get("variant_bitrate") or 0), reverse=True)
            audio_index = audio_streams[0]["index"]

        except Exception as e:
            print("failed to load in ffprobe:", master_playlist_url, e)  # type: ignore
            tried_providers.append(provider)
            return process_url(line)

        if local_probe:
            if abs(local_probe.duration - remote_probe.duration) <= 2.0:  # within 2 seconds  # type: ignore
                print("Already downloaded", output_path)
                sys.exit(0)
            else:
                Path(output_path).unlink()

        if provider == "ST":
            web.download_url(args, master_playlist_url, output_path)  # type: ignore
        elif provider == "TV":
            processes.cmd(
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-headers",
                "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
                "-headers",
                "Referer: https://emturbovid.com/",
                "-i",
                master_playlist_url,  # type: ignore
                "-map",
                f"0:{video_index}",
                "-map",
                f"0:{audio_index}",
                # '-c:v',
                # 'libx265',
                # '-preset',
                # '4',
                "-c:a",
                "libopus",
                "-b:a",
                "96k",
                output_path,
            )

        local_probe = processes.FFProbe(output_path)
        assert local_probe.has_audio
        assert local_probe.has_video
        if abs(local_probe.duration - remote_probe.duration) > 2.0:  # within 2 seconds   # type: ignore
            sys.exit(3)
        corruption = media_check.calculate_corruption(output_path)
        if corruption > 0.1:
            sys.exit(3)
        return None

    process_url(args.path)
    file_utils.tempdir_unlink("*.xpi")


if __name__ == "__main__":
    # cat ~/.jobs/javguru | parallel -j3 --joblog /home/xk/.jobs/joblog_javguru --resume-failed python -m library.scratch.javguru {}
    jav_guru()
