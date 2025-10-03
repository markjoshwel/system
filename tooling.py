"""system/tooling: managing system and user configuration files across different platforms"""

from pathlib import Path
from collections.abc import Generator
from os import getlogin, getenv, makedirs, access, W_OK
from sys import orig_argv, stderr, platform
from typing import Final
from subprocess import run, CalledProcessError
from shutil import which

REPO_ROOT: Final[Path] = Path(__file__).parent
USER: Final[str] = getenv("SYSTEMSET_USER", getlogin())
PREFIX: Final[str] = getenv("SYSTEMSET_PREFIX", "")
IS_DARWIN: Final[bool] = platform == "darwin"


def _iterate_root() -> Generator[Path, None, None]:
    """
    iterates over all relevant files in the repository based on platform

    filters out directories, top-level files, .git files, and applies
    platform-specific filtering:
    - on darwin: only yields files in @darwin and home directories
    - on non-darwin: yields all files except those in @darwin directory

    returns: `Generator[Path, None, None]`
        generator yielding Path objects for each relevant repository file
    """
    darwin_dir = str(REPO_ROOT.joinpath("@darwin"))
    home_dir = str(REPO_ROOT.joinpath("home"))

    for file in REPO_ROOT.rglob("*"):
        # 0. no directories
        if not file.is_file():
            continue

        # 1. no top-level files
        if file.parent == REPO_ROOT:
            continue

        # 2. no .git
        if str(REPO_ROOT.joinpath(".git")) in str(file):
            continue

        # 3. platform-specific filtering
        file_str = str(file)
        if IS_DARWIN:
            # on darwin: only care about @darwin and home
            if not (darwin_dir in file_str or home_dir in file_str):
                continue
        else:
            # on non-darwin: ignore @darwin/*
            if darwin_dir in file_str:
                continue

        yield file


def _map_path(file: Path) -> Path:
    """
    maps a virtual repository file path to its mapped real/target/system location

    applies transformations in order:
    1. ./@darwin/<file path> -> <prefix>/<file path>
    2. ./home/<file> -> <prefix>/Users/<username>/<file> (darwin)
                     -> <prefix>/home/<username>/<file> (non-darwin)
    3. ./<any other> -> <prefix>/<any other>

    arguments:
        `file: Path`
            path to a file in the repository

    returns: `Path`
        mapped path where the file should be placed on the system
    """
    file_str = str(file)

    # 1. fix up @darwin
    # ./@darwin/<file path> -> <prefix>/<file path>
    if (darwin := str(REPO_ROOT.joinpath("@darwin"))) in file_str:
        file_str = file_str.replace(f"{darwin}/", f"{PREFIX}/")

    # 2. fix up home (after @darwin so @darwin/home works)
    # ./home/<file> -> <prefix>/Users/<username>/<file> (darwin)
    #               -> <prefix>/home/<username>/<file> (non-darwin)
    if (home := str(REPO_ROOT.joinpath("home"))) in file_str:
        home_base = "/Users" if IS_DARWIN else "/home"
        return Path(file_str.replace(home, f"{PREFIX}{home_base}/{USER}"))
    else:
        return Path(file_str.replace(str(REPO_ROOT), PREFIX))


def set() -> int:
    """
    copies all virtual repository files to their mapped real system locations

    iterates through all relevant files and writes them to their mapped target
    locations, creating parent directories as needed

    if `--dry` is passed, no actual actions are performed

    returns: `int`
        exit code (number of errors encountered)
    """
    print(
        "system/set",
        f" -> root is {REPO_ROOT}",
        f" -> user is {USER}",
        f" -> prefix is {PREFIX}\n" if PREFIX else "",
        sep="\n",
    )

    errors: list[tuple[Path, Path, str]] = []

    for virtual_file in _iterate_root():
        mapped_real_file: Path = _map_path(virtual_file)

        if "--dry" in orig_argv:
            print(
                " ...",
                virtual_file.relative_to(REPO_ROOT),
                "->",
                mapped_real_file,
                "(skipped)",
            )
            continue

        try:
            # check parent directory permissions
            if not mapped_real_file.parent.exists():
                # find the first existing parent to check write permissions
                parent = mapped_real_file.parent
                while not parent.exists() and parent != parent.parent:
                    parent = parent.parent

                if not access(parent, W_OK):
                    raise PermissionError(f"no write permission for {parent}")

                makedirs(mapped_real_file.parent, exist_ok=True)  # mkdir -p

            elif not access(mapped_real_file.parent, W_OK):
                raise PermissionError(
                    f"no write permission for {mapped_real_file.parent}"
                )

            # check if file exists and is writable
            if mapped_real_file.exists() and not access(mapped_real_file, W_OK):
                raise PermissionError(f"no write permission for {mapped_real_file}")

            content = virtual_file.read_bytes()
            _ = mapped_real_file.write_bytes(content)
            print(" ...", mapped_real_file, "(ok)")

        except Exception as exc:
            print(" !!!", mapped_real_file, f"(error: {exc})")
            errors.append((virtual_file, mapped_real_file, str(exc)))

    # summary
    if errors:
        print(f"\nfound {len(errors)} error(s) while setting files:")
        for repo_file, mapped_real_file, reason in errors:
            print(f"  - {repo_file.relative_to(REPO_ROOT)} ({reason})")
    else:
        print("\nall files set successfully!")

    return len(errors)


def status() -> int:
    """
    uses a system hashing tool to see which virtual and real files are different

    in order it attempts to resolve:
    - xxhsum (xxHash)
    - sha256sum (SHA-256)
    - md5sum (MD5)

    then it traverses `_iterate_root()`, maps each virtual file to its real counterpart,
    with `_map_path` to resolve the real path, and compares their hashes.

    returns: `int`
        exit code (number of differences + missing files + errors)
    """
    # find available hashing tool
    hash_cmd = None
    for cmd in ["xxhsum", "sha256sum", "md5sum"]:
        if which(cmd):
            hash_cmd = cmd
            break

    if not hash_cmd:
        print(
            "error: no hashing tool found (tried xxhsum, sha256sum, md5sum)",
            file=stderr,
        )
        return 1

    print(
        "system/status",
        f" -> root is {REPO_ROOT}\n",
        f" -> user is {USER}\n",
        f" -> prefix is {PREFIX}\n" if PREFIX else "",
        f" -> using {hash_cmd} for hashing\n",
        sep="",
    )

    def get_hash(file_path: Path) -> str | None:
        """compute hash of a file using the selected hashing tool"""
        try:
            result = run(
                [hash_cmd, str(file_path)], capture_output=True, text=True, check=True
            )
            # hash output format: "<hash>  <filename>"
            return result.stdout.split()[0]
        except (CalledProcessError, FileNotFoundError, IndexError):
            return None

    missing: list[tuple[Path, Path]] = []
    different: list[tuple[Path, Path]] = []
    identical: list[tuple[Path, Path]] = []
    errors: list[tuple[Path, Path, str]] = []

    for virtual_file in _iterate_root():
        mapped_real_file: Path = _map_path(virtual_file)

        try:
            # check if real file exists
            if not mapped_real_file.exists():
                print(" ...", mapped_real_file, "(missing)")
                missing.append((virtual_file, mapped_real_file))
                continue

            # compute hashes
            virtual_hash = get_hash(virtual_file)
            real_hash = get_hash(mapped_real_file)

            if virtual_hash is None:
                raise Exception(f"failed to hash virtual file {virtual_file}")
            if real_hash is None:
                raise Exception(f"failed to hash real file {mapped_real_file}")

            # compare hashes
            if virtual_hash == real_hash:
                print(" ...", mapped_real_file, "(ok)")
                identical.append((virtual_file, mapped_real_file))
            else:
                print(" !!!", mapped_real_file, "(different)")
                different.append((virtual_file, mapped_real_file))

        except Exception as exc:
            print(" !!!", mapped_real_file, f"(error: {exc})")
            errors.append((virtual_file, mapped_real_file, str(exc)))

    # summary
    total = len(missing) + len(different) + len(identical) + len(errors)
    print(
        f"\nchecked {total} file(s):",
        f"  - {len(identical)} identical",
        f"  - {len(different)} different",
        f"  - {len(missing)} missing",
        f"  - {len(errors)} error(s)",
        sep="\n"
    )

    if different:
        print("\ndifferent files:")
        for virtual_file, mapped_real_file in different:
            print(f"  - {virtual_file.relative_to(REPO_ROOT)} -> {mapped_real_file}")

    if missing:
        print("\nmissing files:")
        for virtual_file, mapped_real_file in missing:
            print(f"  - {virtual_file.relative_to(REPO_ROOT)} -> {mapped_real_file}")

    if errors:
        print("\nerrors:")
        for virtual_file, mapped_real_file, reason in errors:
            print(f"  - {virtual_file.relative_to(REPO_ROOT)} ({reason})")

    # final message
    if not errors and not different and not missing:
        print("\nall files are the same!")
    else:
        message_parts: list[str] = []
        if errors:
            message_parts.append("there were errors checking files")
        if different:
            message_parts.append("some files are different")
        if missing:
            message_parts.append("some files are missing")

        print("\n", ", and ".join(message_parts), "...",sep="")

    return len(different) + len(missing) + len(errors)


def sync() -> int:
    print("error: not implemented", file=stderr)
    return 1


def main() -> int:
    """command line entry point"""
    match [arg for arg in orig_argv[2:] if not arg.startswith("-")]:
        case ["set"]:
            return set()
        case ["status"]:
            return status()
        case ["sync"]:
            return sync()
        case _:
            print(
                f"usage: {orig_argv[0]} {orig_argv[1]} (set|status|sync) [--dry]",
                file=stderr,
            )
            return 1


if __name__ == "__main__":
    exit(main())
