import argparse, time
from pathlib import Path

from xklb.utils import file_utils, path_utils, processes, web


def javtiful() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("path")
    args = parser.parse_args()

    from pyvirtualdisplay.display import Display
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options

    def process_url(line):
        url = line.rstrip("\n")
        if url in ["", '""', "\n"]:
            return

        display = Display(visible=False, size=(1280, 720))
        display.start()

        options = Options()
        options.set_preference("media.volume_scale", "0.0")
        driver = webdriver.Firefox(options=options)
        try:
            driver.install_addon(str(Path("~/.local/lib/ublock_origin.xpi").expanduser().resolve()))

            driver.get(url)
            driver.implicitly_wait(5)

            title = driver.find_element(By.CSS_SELECTOR, "h1.video-title").text.replace("/", "-").replace("\\", "-")
            target_dir = Path.cwd() / "javtiful"
            target_dir.mkdir(exist_ok=True)
            output_path = path_utils.clean_path(bytes(target_dir / f"{title}.mp4"), max_name_len=255)

            stream_btn = driver.find_element(By.CLASS_NAME, "x-video-btn")
            stream_btn.click()

            time.sleep(3)
            video_element = driver.find_element(By.ID, "hls-video")
            master_playlist_url = video_element.get_attribute("src")

        finally:
            driver.quit()
            display.stop()

        web.download_url(master_playlist_url, output_path)

        local_probe = processes.FFProbe(output_path)
        assert local_probe.has_audio
        assert local_probe.has_video
        # if decode_full_scan(output_path) > 1:
        #     exit(3)

    process_url(args.path)
    file_utils.tempdir_unlink("*.xpi")


if __name__ == "__main__":
    # cat ~/.jobs/javtiful | parallel -j16 --joblog /home/xk/.jobs/joblog_javtiful --shuf --resume-failed python -m xklb.scratch.javtiful {}
    javtiful()
