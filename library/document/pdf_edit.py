#!/usr/bin/python3

import argparse, io
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, devices, shell_utils

DEFAULT_IMAGE_ADJUSTMENT = 100
DEFAULT_POSTERIZE_BITS = 8


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.pdf_edit)
    parser.add_argument(
        "--autolevels",
        "--equalize",
        "-A",
        action="store_true",
        help="Use caution when applying across many different files",
    )
    parser.add_argument(
        "--autocontrast",
        "-AC",
        nargs="?",
        const="0.001",
        help="""--autocontrast 5 means trim 5%% of values from the bottom and top of the histogram.
--autocontrast 1,4 means trim 1%% of values from the bottom and 4%% from the top of the histogram
--autocontrast 4,1 means trim 4%% of values from the bottom and 1%% from the top of the histogram""",
    )
    parser.add_argument(
        "--autotone",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preserve image tone in Photoshop-like style autocontrast",
    )

    parser.add_argument("--brightness", "-b", type=int, default=DEFAULT_IMAGE_ADJUSTMENT)
    parser.add_argument("--contrast", "-c", type=int, default=DEFAULT_IMAGE_ADJUSTMENT)
    parser.add_argument("--color", "--saturation", "-C", type=int, default=DEFAULT_IMAGE_ADJUSTMENT)
    parser.add_argument("--sharpness", "-s", type=int, default=DEFAULT_IMAGE_ADJUSTMENT)

    parser.add_argument("--flip", action="store_true")
    parser.add_argument("--grayscale", action="store_true")
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument(
        "--posterize", type=int, default=DEFAULT_POSTERIZE_BITS, help="Reduce the number of bits for each color channel"
    )

    parser.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--output-path", "-o", help="Output PDF file (optional)")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


def _get_output_path(args, input_path):
    if args.output_path:
        return Path(args.output_path)

    params: list[str] = []
    if args.autolevels:
        params.append("A")
    if args.autocontrast:
        params.append(f"AC{', '.join(args.autocontrast)}")
        if not args.autotone:
            params.append("nT")

    for option, prefix in (("contrast", "c"), ("brightness", "b"), ("color", "C"), ("sharpness", "s")):
        value = getattr(args, option)
        if value != DEFAULT_IMAGE_ADJUSTMENT:
            params.append(f"{prefix}{value}")

    params.extend(method for method in ["flip", "grayscale", "invert", "mirror"] if getattr(args, method))
    if args.posterize < DEFAULT_POSTERIZE_BITS:
        params.append(f"p{args.posterize}")

    return input_path.with_suffix("." + ".".join(params) + ".pdf")


def _process_image(args, img, image_enhance, image_ops):
    if args.autocontrast:
        autocontrast = tuple(float(s) for s in args.autocontrast.split(","))
        if len(autocontrast) == 1:
            autocontrast *= 2
        img = image_ops.autocontrast(img, autocontrast, preserve_tone=args.autotone)  # type: ignore

    if args.autolevels:
        img = image_ops.equalize(img)

    for method in ["Brightness", "Contrast", "Color", "Sharpness"]:
        value = getattr(args, method.lower())
        if value != DEFAULT_IMAGE_ADJUSTMENT:
            enhancer = getattr(image_enhance, method)(img)
            img = enhancer.enhance(value / DEFAULT_IMAGE_ADJUSTMENT)

    if args.posterize < DEFAULT_POSTERIZE_BITS:
        img = image_ops.posterize(img, args.posterize)

    for method in ["flip", "grayscale", "invert", "mirror"]:
        if getattr(args, method):
            img = getattr(image_ops, method)(img)

    out_img_bytes = io.BytesIO()
    img.save(out_img_bytes, format="JPEG")
    return out_img_bytes.getvalue()


def process_path(args, input_path):
    import img2pdf, ocrmypdf, pdf2image
    from PIL import ImageEnhance, ImageOps
    from tqdm import tqdm

    input_path = Path(input_path)
    output_path = _get_output_path(args, input_path)
    if args.simulate:
        print("pdf-edit", input_path, output_path)
        return

    input_images = pdf2image.convert_from_path(input_path)
    print(f"Loaded {len(input_images)} pages")
    output_images = [_process_image(args, img, ImageEnhance, ImageOps) for img in tqdm(input_images, unit="pages")]

    if input_path != output_path:
        output_path = devices.clobber_new_file(args, output_path)

    print(f"Saving {output_path}")
    with open(output_path, "wb") as outf:
        img2pdf.convert(*output_images, outputstream=outf)

    if args.ocr:
        ocrmypdf.ocr(output_path, output_path, deskew=True, optimize=1)


def pdf_edit():
    args = parse_args()

    for path in shell_utils.gen_paths(args, ["pdf"]):
        process_path(args, path)
