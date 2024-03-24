import ast, importlib.util
from pathlib import Path


def extract_imports(file_path):
    with open(file_path, encoding="utf-8") as file:
        try:
            tree = ast.parse(file.read(), filename=file_path)
        except SyntaxError:
            return set()

        imports = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)

        return imports


def find_missing_modules(paths):
    checked_modules = set()
    missing_modules = set()
    for path in paths:
        modules = extract_imports(path)
        for module in modules:
            module = module.split(".")[0]
            if module in checked_modules:
                continue

            try:
                importlib.import_module(module)
            except ModuleNotFoundError:
                missing_modules.add(module)
            checked_modules.add(module)

    return missing_modules


def test_modules():
    missing = find_missing_modules(Path("xklb").rglob("*.py"))

    if missing:
        print("Missing modules:")
        for module in missing:
            print(module)
        raise RuntimeError(missing)
    else:
        print("No missing modules found.")
