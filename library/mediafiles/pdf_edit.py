#!/usr/bin/python3

import argparse, io
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, devices, file_utils


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

    parser.add_argument("--brightness", "-b", type=int, default=100)
    parser.add_argument("--contrast", "-c", type=int, default=100)
    parser.add_argument("--color", "--saturation", "-C", type=int, default=100)
    parser.add_argument("--sharpness", "-s", type=int, default=100)

    parser.add_argument("--flip", action="store_true")
    parser.add_argument("--grayscale", action="store_true")
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument("--posterize", type=int, default=8, help="Reduce the number of bits for each color channel")

    parser.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--output-path", "-o", help="Output PDF file (optional)")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


def process_path(args, input_path):
    import img2pdf, ocrmypdf, pdf2image
    from PIL import ImageEnhance, ImageOps
    from tqdm import tqdm

    input_path = Path(input_path)
    output_path = Path(args.output_path) if args.output_path else None

    if output_path is None:
        params: list[str] = []
        if args.autolevels:
            params.append("A")
        if args.autocontrast:
            params.append(f"AC{', '.join(args.autocontrast)}")
            if not args.autotone:
                params.append("nT")

        if args.contrast != 100:
            params.append(f"c{args.contrast}")
        if args.brightness != 100:
            params.append(f"b{args.brightness}")
        if args.color != 100:
            params.append(f"C{args.color}")
        if args.sharpness != 100:
            params.append(f"s{args.sharpness}")

        for method in ["flip", "grayscale", "invert", "mirror"]:
            val = getattr(args, method)
            if val:
                params.append(method)

        if args.posterize < 8:
            params.append(f"p{args.posterize}")

        suffix = "." + ".".join(params) + ".pdf"
        output_path = input_path.with_suffix(suffix)

    input_images = pdf2image.convert_from_path(input_path)
    print(f"Loaded {len(input_images)} pages")

    output_images: list[bytes] = []
    for img in tqdm(input_images, unit="pages"):
        if args.autocontrast:
            autocontrast = tuple(float(s) for s in args.autocontrast.split(","))
            if len(autocontrast) == 1:
                autocontrast *= 2  # duplicate the item; make the tuple size of two
            img = ImageOps.autocontrast(img, autocontrast, preserve_tone=args.autotone)  # type: ignore

        if args.autolevels:
            img = ImageOps.equalize(img)

        for method in ["Brightness", "Contrast", "Color", "Sharpness"]:
            val = getattr(args, method.lower())
            if val != 100:
                enhancer = getattr(ImageEnhance, method)(img)
                img = enhancer.enhance(val / 100)

        if args.posterize < 8:
            img = ImageOps.posterize(img, args.posterize)

        for method in ["flip", "grayscale", "invert", "mirror"]:
            val = getattr(args, method)
            if val:
                img = getattr(ImageOps, method)(img)

        out_img_bytes = io.BytesIO()
        img.save(out_img_bytes, format="JPEG")
        output_images.append(out_img_bytes.getvalue())

    if input_path != output_path:
        output_path = devices.clobber_new_file(args, output_path)

    print(f"Saving {output_path}")

    with open(output_path, "wb") as outf:
        img2pdf.convert(*output_images, outputstream=outf)

    if args.ocr:
        ocrmypdf.ocr(output_path, output_path, deskew=True, optimize=1)


def pdf_edit():
    args = parse_args()

    for path in file_utils.gen_paths(args, ["pdf"]):
        process_path(args, path)
