#!/usr/bin/python3

import io
from pathlib import Path
from typing import List

from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.pdf_edit)
    parser.add_argument("--brightness", "-b", type=int, default=100)
    parser.add_argument("--contrast", "-c", type=int, default=100)
    parser.add_argument("--color-contrast", "--color", "-C", type=int, default=100)
    parser.add_argument("--sharpness", "-s", type=int, default=100)
    parser.add_argument("--no-ocr", "--skip-ocr", dest="ocr", action="store_false")

    parser.add_argument("--output-path", "-o", help="Output PDF file (optional)")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


def process_path(args, input_path):
    import img2pdf, ocrmypdf, pdf2image
    from PIL import ImageEnhance
    from tqdm import tqdm

    input_path = Path(input_path)
    output_path = Path(args.output_path) if args.output_path else None

    if output_path is None:
        params: List[str] = []
        if args.contrast != 100:
            params.append(f"c{args.contrast}")
        if args.brightness != 100:
            params.append(f"b{args.brightness}")
        if args.color_contrast != 100:
            params.append(f"C{args.color_contrast}")
        if args.sharpness != 100:
            params.append(f"s{args.sharpness}")

        suffix = "." + ".".join(params) + ".pdf"
        output_path = input_path.with_suffix(suffix)

    input_images = pdf2image.convert_from_path(input_path)
    print(f"Loaded {len(input_images)} pages")

    output_images: list[bytes] = []
    for img in tqdm(input_images, unit="pages"):
        for method in ["Brightness", "Contrast", "Color", "Sharpness"]:
            val = getattr(args, method.lower())
            if val != 100:
                enhancer = getattr(ImageEnhance, method)(img)
                img = enhancer.enhance(val / 100)

        out_img_bytes = io.BytesIO()
        img.save(out_img_bytes, format="JPEG")
        output_images.append(out_img_bytes.getvalue())

    print(f"Saving {output_path}")

    with open(output_path, "wb") as outf:
        img2pdf.convert(*output_images, outputstream=outf)

    if args.ocr:
        ocrmypdf.ocr(output_path, output_path, deskew=True, optimize=1)


def pdf_edit():
    args = parse_args()

    for path in arg_utils.gen_paths(args, ["pdf"]):
        process_path(args, path)
