from argparse import ArgumentParser
from pathlib import Path

import pyperclip


def get_code_together(path: str | Path, pattern: str = "*.py") -> str:
    """Combine source files from a file or directory into one string."""
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"File or directory not found: {path}")

    if path.is_file():
        paths = [path]
    else:
        paths = sorted(path.rglob(pattern), key=lambda p: str(p))

    code_together = []

    for file_path in paths:
        code = file_path.read_text(encoding="utf-8")
        code_together.append(f"\n\n# File: {file_path}\n{code}")

    return "".join(code_together)


def main() -> None:
    parser = ArgumentParser(description="Combine source files into a single output.")

    parser.add_argument(
        "path",
        type=Path,
        help="Path to a file or directory.",
    )

    parser.add_argument(
        "-p",
        "--pattern",
        default="*.py",
        help="Glob pattern for files to include (default: *.py).",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write output to a file.",
    )

    parser.add_argument(
        "-c",
        "--clipboard",
        action="store_true",
        help="Copy the combined code directly to the clipboard.",
    )

    args = parser.parse_args()

    code = get_code_together(args.path, args.pattern)

    if args.clipboard:
        pyperclip.copy(code)
        print("✓ Code copied to clipboard.")

    if args.output:
        args.output.write_text(code, encoding="utf-8")
        print(f"✓ Code written to {args.output}")

    if not args.clipboard and not args.output:
        print(code)


if __name__ == "__main__":
    main()
