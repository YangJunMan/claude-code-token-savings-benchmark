import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_manifest(roots, exclude=()):
    excluded = {Path(path).resolve() for path in exclude}
    files = sorted(
        path for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.resolve() not in excluded
    )
    return "".join(f"{digest(path)}  {path}\n" for path in files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_manifest(args.roots, exclude=(args.output,)))


if __name__ == "__main__":
    main()
