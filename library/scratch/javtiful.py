import sys, time, warnings
from pathlib import Path

from library.mediafiles import media_check
from library.utils import arggroups, argparse_utils, file_utils, path_utils, processes, web


def javtiful() -> None:
    warnings.warn(
        "This subcommand will likely be removed in future versions--"
        "Unless enough people complain or a generous benefactor appears",
        DeprecationWarning,
        stacklevel=2,
    )

    parser = argparse_utils.ArgumentParser()
    arggroups.selenium(parser)
    arggroups.download(parser)
    arggroups.debug(parser)

    parser.add_argument("path")
    args = parser.parse_args()
    arggroups.selenium_post(args)

    from selenium.webdriver.common.by import By

    def process_url(line):
        url = line.rstrip("\n")
        if url in ["", '""', "\n"]:
            return

        web.load_selenium(args)
        try:
            args.driver.get(url)
            args.driver.implicitly_wait(5)

            title = (
                args.driver.find_element(By.CSS_SELECTOR, "h1.video-title").text.replace("/", "-").replace("\\", "-")
            )
            target_dir = Path.cwd() / "javtiful"
            target_dir.mkdir(exist_ok=True)
            output_path = path_utils.clean_path(bytes(target_dir / f"{title}.mp4"), max_name_len=255)

            stream_btn = args.driver.find_element(By.CLASS_NAME, "x-video-btn")
            stream_btn.click()

            time.sleep(3)
            video_element = args.driver.find_element(By.ID, "hls-video")
            master_playlist_url = video_element.get_attribute("src")

        finally:
            web.quit_selenium(args)

        web.download_url(args, master_playlist_url, output_path)

        local_probe = processes.FFProbe(output_path)
        assert local_probe.has_audio
        assert local_probe.has_video
        corruption = media_check.calculate_corruption(output_path)
        if corruption > 0.1:
            sys.exit(3)

    process_url(args.path)
    file_utils.tempdir_unlink("*.xpi")


if __name__ == "__main__":
    # cat ~/.jobs/javtiful | parallel -j16 --joblog /home/xk/.jobs/joblog_javtiful --shuf --resume-failed python -m library.scratch.javtiful {}
    javtiful()
