import itertools, os
from pathlib import Path
from types import ModuleType

import gallery_dl
from gallery_dl.exception import StopExtraction
from gallery_dl.extractor.message import Message
from gallery_dl.job import Job
from gallery_dl.util import build_duration_func

from xklb import db_media, db_playlists
from xklb.utils import consts, printing, strings
from xklb.utils.log_utils import log

gallery_dl = None


def load_module_level_gallery_dl(args) -> ModuleType:
    global gallery_dl

    if gallery_dl is None:
        import gallery_dl

        gallery_dl.config.load()

        download_archive = Path(args.download_archive or "~/.local/share/gallerydl.sqlite3").expanduser().resolve()
        if download_archive.exists():
            gallery_dl.config.set(("extractor",), "archive", str(download_archive))

        if hasattr(args, "prefix"):
            gallery_dl.config.set(("extractor",), "base-directory", args.prefix)
        gallery_dl.config.set(("extractor",), "parent-directory", False)
        gallery_dl.config.set(
            ("extractor",),
            "directory",
            [
                "{user[account]|username|account[username]|user[id]|account[id]|subcategory}",
                "{category}",
                "{original_title[0]|title[0]|filename[0]}",
                "{original_title[1]|title[1]|filename[1]}",
            ],
        )
        gallery_dl.config.set(
            ("extractor",),
            "filename",
            "{filename[:100]|title[:100]|original_title[:100]|id[:100]}.{extension}",
        )
        gallery_dl.config.set(("extractor",), "browser", "firefox")

        if consts.PYTEST_RUNNING:
            gallery_dl.config.set(("extractor",), "download", False)

    return gallery_dl


def is_supported(args, url) -> bool:
    if getattr(is_supported, "extractors", None) is None:
        gallery_dl = load_module_level_gallery_dl(args)
        is_supported.extractors = gallery_dl.extractor.extractors()

    return any(ie.pattern.match(url) and ie.category != "generic" for ie in is_supported.extractors)


def parse_gdl_job_status(job_status, path, ignore_errors=False):
    errors = []

    if job_status & 1:
        errors.append("UnspecifiedError")
        log.error("[%s]: gallery_dl gave an UnspecifiedError.", path)

    if job_status & 64:  # no extractor
        errors.append("NoExtractorError")
        log.info("[%s]: NoExtractorError", path)

    if job_status & 16 or job_status & 32:
        if job_status & 16:
            errors.append("AuthorizationError")
        if job_status & 32:
            errors.append("FilterError")
        log.info("[%s]: Recoverable error(s) matched (will try again later)", path)

    if job_status & 4 or job_status & 8:  # HTTPError; not found / 404
        # TODO: distinguish between 429 and other errors
        # depending on extractor this can be fixed upstream
        # or by reading gallery_dl log stream
        error = "HTTPError"
        if job_status & 8:
            error = "HTTPNotFoundError"
        errors.append(error)
        log.debug("[%s]: Unrecoverable error %s. %s", path, error, strings.combine(errors))

    if job_status & 128:
        errors.append("OSOrJSONDecodeError")
        # https://github.com/mikf/gallery-dl/issues/4380
        # if not ignore_errors:
        # raise OSError
    if job_status & 2:
        raise ValueError("gallery_dl configuration error")

    return errors


def download(args, m):
    gallery_dl = load_module_level_gallery_dl(args)

    extensions = []
    if args.photos:
        extensions.extend(["jpg", "jpeg", "webp"])
    if args.drawings:
        extensions.extend(["png", "svg", "webp"])
    if args.gifs:
        extensions.extend(["gif", "mp4", "m4v", "webm"])

    if extensions:
        quoted_extensions = ",".join(f"'{ext}'" for ext in extensions)
        gallery_dl.config.set(("extractor",), "image-filter", f"extension in ({quoted_extensions})")

    webpath = m["path"]

    try:
        job = gallery_dl.job.DownloadJob(webpath)
    except gallery_dl.exception.NoExtractorError:
        log.info("[%s]: NoExtractorError", webpath)  # RecoverableError
        db_media.download_add(args, webpath, error="NoExtractorError")
        return

    job_status = job.run()
    errors = parse_gdl_job_status(job_status, webpath, ignore_errors=args.ignore_errors)

    info = getattr(job.pathfmt, "kwdict", None)
    if info:
        info["path"] = webpath

    local_path = getattr(job.pathfmt, "path", "") or None
    db_media.download_add(
        args,
        webpath,
        info,
        local_path=local_path,
        error=strings.combine(errors),
        unrecoverable_error="HTTPNotFoundError" in errors,
    )


class GeneratorJob(Job):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(super(), "_init"):
            super()._init()
        self.dispatched = False
        self.visited = set()
        self.status = 0

    def message_generator(self):
        extractor = self.extractor
        sleep = build_duration_func(extractor.config("sleep-extractor"))
        if sleep:
            extractor.sleep(sleep(), "extractor")

        try:
            for msg in extractor:
                self.dispatch(msg)
                if self.dispatched:
                    yield msg
                    self.dispatched = False
        except StopExtraction:
            pass

    def run(self):
        for msg in self.message_generator():
            ident, url, kwdict = msg
            if ident == Message.Url:
                yield (msg[1], msg[2])

            elif ident == Message.Queue:
                if url in self.visited:
                    continue
                self.visited.add(url)

                cls = kwdict.get("_extractor")
                if cls:
                    extr = cls.from_url(url)
                else:
                    extr = self.extractor.find(url)

                if extr:
                    job = self.__class__(extr, self)
                    for webpath, info in job.run():
                        yield (webpath, info)
            else:
                raise TypeError

    def handle_url(self, url, kwdict):
        self.dispatched = True

    def handle_queue(self, url, kwdict):
        self.dispatched = True


def get_playlist_metadata(args, playlist_path):
    gallery_dl = load_module_level_gallery_dl(args)

    added_media_count = 0
    job = GeneratorJob(playlist_path)
    gen = job.run()

    first_two = list(itertools.islice(gen, 2))
    is_playlist = len(first_two) > 1
    for webpath, info in itertools.chain(first_two, gen):
        errors = parse_gdl_job_status(job.status, playlist_path)
        extractor_key = "gdl_" + job.extractor.category

        if not info:
            log.error("No info returned from image extractor %s", extractor_key)
            raise

        assert webpath
        info["extractor_key"] = extractor_key

        log.debug("webpath == playlist_path" if webpath == playlist_path else "webpath != playlist_path")

        playlist_id = None
        if is_playlist:
            playlist_id = db_playlists.add(args, playlist_path, info)
        else:
            log.warning("Importing playlist-less media %s", playlist_path)

        if db_media.exists(args, webpath):
            log.warning("Media already exists")

        info = {**info, "playlist_id": playlist_id, "webpath": webpath, **args.extra_media_data}
        db_media.playlist_media_add(
            args,
            playlist_path,
            info,
            error=strings.combine(errors),
            unrecoverable_error="HTTPNotFoundError" in errors,
        )

        added_media_count += 1
        if added_media_count > 1:
            printing.print_overwrite(f"[{playlist_path}] Added {added_media_count} media")

    if added_media_count == 0:
        from rich import inspect

        job = gallery_dl.job.DataJob(playlist_path, file=open(os.devnull, "w"), ensure_ascii=False)
        job.run()
        inspect(job.data)
        raise RuntimeError("No data found")

    return added_media_count
