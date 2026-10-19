import argparse
import sys

from bs4 import BeautifulSoup, NavigableString, Tag

from library.utils import arggroups, argparse_utils

USAGE = {
    "markdown": """library text markdown [PATH ...]

    Convert simple HTML documents to readable Markdown. Read stdin when no
    paths are given.
""",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=USAGE["markdown"])
    arggroups.debug(parser)
    parser.add_argument("paths", nargs="*")
    return parser


def _render(node: Tag | NavigableString) -> str:  # noqa: PLR0911
    if isinstance(node, NavigableString):
        return str(node)

    children = "".join(_render(child) for child in node.children)
    name = node.name.lower()

    if name in {"script", "style", "noscript"}:
        return ""
    if name in {"strong", "b"}:
        return f"**{children.strip()}**"
    if name in {"em", "i"}:
        return f"*{children.strip()}*"
    if name == "a":
        href = node.get("href")
        return f"[{children.strip()}]({href})" if href else children
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return f"{'#' * int(name[1])} {children.strip()}\n\n"
    if name == "br":
        return "\n"
    if name == "code" and node.parent and node.parent.name != "pre":
        return f"`{children.strip()}`"
    if name == "pre":
        code = node.get_text().strip("\n")
        return f"\n```\n{code}\n```\n\n"
    if name == "li":
        return f"- {children.strip()}\n"
    if name in {"p", "div", "section", "article", "blockquote", "ul", "ol"}:
        return f"{children.strip()}\n\n"
    return children


def markdown_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup
    result = _render(root)
    result = "\n".join(line.rstrip() for line in result.splitlines())
    result = "\n".join(line for line in result.splitlines() if line.strip() or (line == "" and result))
    return result.strip() + ("\n" if result.strip() else "")


def markdown() -> None:
    parser = _parser()
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    paths = args.paths or ["-"]

    for index, path in enumerate(paths):
        if path == "-":
            html = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as stream:
                html = stream.read()
        if index:
            print()
        sys.stdout.write(markdown_text(html))
