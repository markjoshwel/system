# system/set: set the rootfiles and dotfiles forcibly, using hard links

from pathlib import Path
from collections.abc import Generator
from os import getlogin, getenv, makedirs
from sys import orig_argv, stderr
from typing import Final

ROOT: Final[Path] = Path(__file__).parent
USER: Final[str] = getenv("SYSTEMSET_USER", getlogin())
PREFIX: Final[str] = getenv("SYSTEMSET_PREFIX", "")


def iterate_root() -> Generator[Path, None, None]:
    for file in ROOT.rglob("*"):
        # 0. no directories
        if not file.is_file():
            continue

        # 1. no top-level files
        if file.parent == ROOT:
            continue

        # 2. no .git
        if str(ROOT.joinpath(".git")) in str(file):
            continue

        yield file


def map_path(file: Path) -> Path:
    # 1. fix up home
    # ./home/<file> -> <prefix>/home/<username>/<file>
    if (home := str(ROOT.joinpath("home"))) in str(file):
        return Path(str(file).replace(home, f"{PREFIX}/home/{USER}"))
    else:
        return Path(str(file).replace(str(ROOT), PREFIX))


def set():
    print(
        "system/set",
        f" -> root is {ROOT}",
        f" -> user is {USER}",
        f" -> prefix is {PREFIX}\n" if PREFIX else "",
        sep="\n",
    )

    for file in iterate_root():
        mapped_file: Path = map_path(file)
        print(" ...", file, "->", mapped_file)

        if not mapped_file.parent.exists():
            makedirs(mapped_file.parent, exist_ok=True)  # mkdir -p

        if "--dry" not in orig_argv:
            content = file.read_text(encoding="utf-8")
            _ = mapped_file.write_text(content, encoding="utf-8")
            

def main():
    match orig_argv:
        case [_, "set"]:
            set()
        case _:
            print(f"usage: {orig_argv[0]} {orig_argv[1]} set [--dry]", file=stderr)


if __name__ == "__main__":
    main()
