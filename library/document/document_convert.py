import argparse, io, os, shlex, sys, tempfile
from pathlib import Path
from shutil import which

from library import usage
from library.image import images_to_pdf
from library.utils import arggroups, argparse_utils, consts, devices, file_utils, path_utils, processes, shell_utils, web
from library.utils.log_utils import log


TEXT_EXTENSIONS = (
    consts.PLAIN_EXTENSIONS
    | consts.TEXTRACT_EXTENSIONS
    | consts.CALIBRE_EXTENSIONS
    | {"md", "markdown", "rst", "text", "txt"}
)
IMAGE_EXTENSIONS = (consts.IMAGE_EXTENSIONS | consts.PIL_EXTENSIONS) - {"pdf"}
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | {"pdf"}


def build_parser(usage_text: str) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage_text)
    parser.add_argument("--ocr", action="store_true", help="Run OCRmyPDF on the generated PDF")
    parser.add_argument(
        "--open",
        dest="open_output",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Open generated PDFs with dragondrop",
    )
    parser.add_argument("--output-path", "-o", help="Output PDF file (only valid for one input group)")
    parser.add_argument("--delete-original", action="store_true", help="Delete inputs after successful conversion")
    arggroups.clobber(parser)
    arggroups.requests(parser)
    arggroups.download(parser, profile=False)
    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def parse_args() -> argparse.Namespace:
    return build_parser(usage.document_convert)


def _require_commands(*commands: str) -> None:
    missing = [command for command in commands if which(command) is None]
    if missing:
        names = ", ".join(missing)
        print(f"Required command(s) not found: {names}", file=sys.stderr)
        raise SystemExit(1)


def _document_kind(path: str) -> str:
    ext = path_utils.ext(path)
    kind = None
    if ext == "pdf":
        kind = "pdf"
    elif ext in TEXT_EXTENSIONS:
        kind = "text"
    elif ext in IMAGE_EXTENSIONS:
        kind = "image"
    if kind is not None:
        return kind

    mimetype = (file_utils.detect_mimetype(path) or "").lower()
    if "pdf" in mimetype:
        kind = "pdf"
    elif mimetype.startswith("image/") or " image" in mimetype:
        kind = "image"
    elif mimetype.startswith("text/") or mimetype in {"markdown", "plain", "plaintext"}:
        kind = "text"
    return kind or "unknown"


def _download(path: str, args) -> str | None:
    if not path.startswith(("http://", "https://", "ftp://")):
        return path
    if args.simulate:
        log.info("Downloading %s", path)
        return path
    return web.download_url(args, path)


def _expand_paths(args) -> list[str]:
    paths = []
    for raw_path in args.paths:
        path = _download(raw_path, args)
        if path is None:
            log.error("Could not save URL %s", raw_path)
            continue

        if path.startswith(("http://", "https://", "ftp://")):
            paths.append(path)
            continue

        resolved = str(Path(path).resolve())
        if os.path.isdir(resolved):
            found = shell_utils.rglob(resolved, DOCUMENT_EXTENSIONS, getattr(args, "exclude", None), quiet=True)[0]
            paths.extend(found)
        else:
            paths.append(resolved)
    return paths


def _output_path(args, path: str, suffix: str = ".pdf") -> Path:
    if args.output_path:
        return Path(args.output_path)
    return Path(path).with_suffix(suffix)


def _open_output(args, path: str) -> None:
    if not args.open_output:
        return
    _require_commands("dragondrop")
    processes.cmd_detach("dragondrop", path)


def _ocr_pdf(args, pdf_path: Path) -> Path:
    if not args.ocr:
        return pdf_path

    _require_commands("gs", "tesseract")
    try:
        import ocrmypdf
    except ModuleNotFoundError:
        print("OCR requires the ocrmypdf Python package", file=sys.stderr)
        raise SystemExit(1) from None

    with tempfile.TemporaryDirectory(prefix="library-ocr-") as temp_dir:
        ocr_path = Path(temp_dir) / pdf_path.name
        ocrmypdf.ocr(pdf_path, ocr_path, deskew=True, optimize=1)
        os.replace(ocr_path, pdf_path)
    return pdf_path


def convert_text_path(args, path: str, output_path: str | None = None) -> str:
    _require_commands("pandoc")
    source = Path(path)
    destination = Path(output_path) if output_path else _output_path(args, path)
    destination = Path(devices.clobber_new_file(args, str(destination)))

    command = ["pandoc", str(source), "-o", str(destination)]
    if path_utils.ext(path) in {"txt", "text", "rst"}:
        command[1:1] = ["--from", "markdown"]

    if args.simulate:
        print(shlex.join(command))
        return str(destination)

    processes.cmd(*command, limit_ram=True, nice=6)
    if not destination.exists():
        message = f"Pandoc did not create {destination}"
        raise FileNotFoundError(message)

    _ocr_pdf(args, destination)
    if args.delete_original and source != destination:
        source.unlink()
    _open_output(args, str(destination))
    log.info("Saved %s", destination)
    return str(destination)


def convert_pdf_path(args, path: str, output_path: str | None = None) -> str:
    _require_commands("pdftoppm")
    import img2pdf, pdf2image

    source = Path(path)
    destination = Path(output_path) if output_path else source.with_name(f"{source.stem}.converted.pdf")
    destination = Path(devices.clobber_new_file(args, str(destination)))

    if args.simulate:
        print("pdf2image", source, "->", destination)
        return str(destination)

    input_images = pdf2image.convert_from_path(source)
    output_images: list[bytes] = []
    for image in input_images:
        image_bytes = io.BytesIO()
        image.save(image_bytes, format="JPEG")
        output_images.append(image_bytes.getvalue())

    with open(destination, "wb") as output_file:
        img2pdf.convert(*output_images, outputstream=output_file)

    _ocr_pdf(args, destination)
    if args.delete_original:
        source.unlink()
    _open_output(args, str(destination))
    log.info("Saved %s", destination)
    return str(destination)


def _convert_paths(args, paths: list[str], mode: str) -> list[str]:
    image_paths = []
    other_paths = []
    for path in paths:
        kind = _document_kind(path)
        if mode == "text" and kind != "text":
            log.error("Not a text-like document: %s", path)
            continue
        if kind == "image":
            image_paths.append(path)
        elif kind in {"text", "pdf"}:
            other_paths.append((path, kind))
        else:
            log.error("Could not identify a supported document type for %s", path)

    groups = (1 if image_paths else 0) + len(other_paths)
    if args.output_path and groups != 1:
        raise SystemExit("--output-path requires exactly one input group")

    outputs = []
    if image_paths:
        image_args = argparse.Namespace(**vars(args))
        image_args.output_path = args.output_path
        output = images_to_pdf.process_paths(image_args, image_paths)
        if output:
            output = _ocr_pdf(args, Path(output))
            _open_output(args, str(output))
            outputs.append(str(output))

    for path, kind in other_paths:
        if kind == "text":
            outputs.append(convert_text_path(args, path))
        else:
            outputs.append(convert_pdf_path(args, path))
    return outputs


def convert_paths(args, mode: str = "auto") -> list[str]:
    paths = _expand_paths(args)
    if not paths:
        raise SystemExit("No input paths found")
    return _convert_paths(args, paths, mode)


def document_convert() -> None:
    args = parse_args()
    convert_paths(args)
