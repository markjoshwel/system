#!/usr/bin/env python3
"""mark's system tooling: cross-platform system and user configuration file manager"""

from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from hashlib import blake2b
from inspect import signature
from json import dumps, loads
from os import W_OK, access, chmod, getenv, getlogin, makedirs
from os.path import expandvars
from pathlib import Path
from platform import system
from shutil import which
from subprocess import CompletedProcess, run
from sys import executable, orig_argv, stderr
from typing import (
    Callable,
    Final,
    Generic,
    NamedTuple,
    ParamSpec,
    TypedDict,
    TypeVar,
    cast,
    override,
)
from warnings import warn

REPO_ROOT: Final[Path] = Path(__file__).parent
USER: Final[str] = getenv("SYSTEMSET_USER", getlogin())
_WINDOWS_SYSTEM_ROOT = expandvars("%SystemRoot%")
PREFIX: Final[str] = getenv(
    key="SYSTEMSET_PREFIX",
    default=(
        (
            str(Path(_WINDOWS_SYSTEM_ROOT).parent)
            if ("WINDOWS" in _WINDOWS_SYSTEM_ROOT)
            else "\\"
        )
        if (system().lower() == "windows")
        else "/"
    ),
)
SLASH: Final[str] = "\\" if (system().lower() == "windows") else "/"

DARWIN_SPECIFIC_DIR_STR = str(REPO_ROOT.joinpath("@darwin"))
WINDOWS_SPECIFIC_DIR_STR = str(REPO_ROOT.joinpath("@windows"))
LINUX_SPECIFIC_DIR_STR = str(REPO_ROOT.joinpath("@linux"))

LOCKFILE_PATH: Final[Path] = REPO_ROOT.joinpath(".system/system.tooling.lock")


ResultType = TypeVar("ResultType")


class Result(NamedTuple, Generic[ResultType]):
    """
    `typing.NamedTuple` representing a result for safe value retrieval

    attributes:
        `value: ResultType`
            value to return or fallback value if erroneous
        `error: BaseException | None = None`
            exception if any

    methods:
        `def __bool__(self) -> bool: ...`
            method for boolean comparison for exception safety
        `def get(self) -> ResultType: ...`
            method that raises or returns an error if the Result is erroneous
        `def cry(self, string: bool = False) -> str: ...`
            method that returns the result value or raises an error
    """

    value: ResultType
    error: BaseException | None = None

    def __bool__(self) -> bool:
        """
        method for boolean comparison for easier exception handling

        returns: `bool`
            that returns True if `self.error` is not None
        """
        return self.error is None

    def cry(self, string: bool = False) -> str:  # noqa: FBT001, FBT002
        """
        method that raises or returns an error if the Result is erroneous

        arguments:
            `string: bool = False`
                if `self.error` is an Exception, returns it as a string
                error message

        returns: `str`
            returns `self.error` as a string if `string` is True,
            or returns an empty string if `self.error` is None
        """

        if isinstance(self.error, BaseException):
            if string:
                message = f"{self.error}"
                name = self.error.__class__.__name__
                return f"{message} ({name})" if (message != "") else name

            raise self.error

        return ""

    def get(self) -> ResultType:
        """
        method that returns the result value or raises an error

        returns: `ResultType`
            returns `self.value` if `self.error` is None

        raises: `BaseException`
            if `self.error` is not None
        """
        if self.error is not None:
            raise self.error
        return self.value


P = ParamSpec("P")
R = TypeVar("R")


def _result_wrap(default: R) -> Callable[[Callable[P, R]], Callable[P, Result[R]]]:
    """decorator that wraps a non-Result-returning function to return a Result"""

    def result_decorator(func: Callable[P, R]) -> Callable[P, Result[R]]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> Result[R]:
            try:
                return Result(func(*args, **kwargs))
            except Exception as exc:
                return Result(default, error=exc)

        return wrapper

    return result_decorator


class MSTLockedFileData(TypedDict):
    mtime: float
    hash: str
    corresponding_git_hash: str


_DefaultMSTLockedFileData = MSTLockedFileData(
    mtime=0.0, hash="", corresponding_git_hash=""
)


MSTLockfileDictType = dict[Path, MSTLockedFileData]


class MSTLockfile(MSTLockfileDictType):
    def purge_dangling_entries(self) -> None:
        """remove MSTLockedFileData entries for non-existent files"""
        for key in list(self.keys()):
            if (not key.exists()) or (not key.is_file()):
                print(
                    f"warning: purging dangling lockfile entry for '{key}' (does not exist or is not a file)",
                    file=stderr,
                )
                del self[key]

    @classmethod
    def loads_json(cls, lockfile_str: str) -> "MSTLockfile":
        """deserialise a json string into a MSTLockfile"""
        if not isinstance(lockfile_dict := loads(lockfile_str), dict):  # pyright: ignore[reportAny]
            raise ValueError("passed in lockfile content string is not a dictionary")

        for key_path in lockfile_dict:  # pyright: ignore[reportUnknownVariableType]
            supposedly_lockedfiledata = lockfile_dict.get(key_path, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportUnknownArgumentType]

            if not isinstance(supposedly_lockedfiledata, dict):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, data is not represented as a dictionary"
                )
            if not all(
                key in supposedly_lockedfiledata
                for key in ("mtime", "hash", "corresponding_git_hash")
            ):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, missing any of the following keys: 'mtime', 'hash', 'corresponding_git_hash'"
                )
            if not isinstance(supposedly_lockedfiledata["mtime"], float):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, 'mtime' is not a float"
                )
            if not isinstance(supposedly_lockedfiledata["hash"], str):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, 'hash' is not a string"
                )
            if not isinstance(supposedly_lockedfiledata["corresponding_git_hash"], str):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, 'corresponding_git_hash' is not a string"
                )

        lockfile: MSTLockfile = cls()
        for key_str, value in lockfile_dict.items():  # pyright: ignore[reportUnknownVariableType]
            lockfile[Path(key_str)] = cast(MSTLockedFileData, value)  # pyright: ignore[reportUnknownArgumentType]

        return lockfile

    def dumps_json(self) -> str:
        """serialise the MSTLockfile object into a json string"""
        return dumps(
            {
                str(lock_path).replace(SLASH, "/"): lock_data
                for lock_path, lock_data in self.items()
            },
            indent=2,
        )

    @classmethod
    def load_from_repo(cls) -> "MSTLockfile":
        """
        loads the MSTLockfile object from the repository,
        returns the MSTLockfile object
        """
        if not LOCKFILE_PATH.exists():
            raise FileNotFoundError("lockfile not found")
        if not LOCKFILE_PATH.is_file():
            raise FileNotFoundError("lockfile is not a file")

        lockfile_text = LOCKFILE_PATH.read_text(encoding="utf-8")
        lockfile = cls.loads_json(lockfile_text)
        lockfile.purge_dangling_entries()
        return lockfile

    def dump_to_repo(self) -> int:
        """
        dumps the MSTLockfile object into the repository, returns the number
        of bytes written

        it may make the parent directory if it does not exist, and may write
        a .gitignore file if it does not exist (of which the bytes are not
        added to the return value)
        """
        if not LOCKFILE_PATH.parent.exists():
            LOCKFILE_PATH.parent.mkdir(parents=True)
            _ = LOCKFILE_PATH.parent.joinpath(".gitignore").write_text(
                "# autogenerated by mark's system tooling, do not edit!\n*\n",
                encoding="utf-8",
            )

        written = LOCKFILE_PATH.write_text(self.dumps_json(), encoding="utf-8")

        # ensure lockfile is owned by the actual user, not root if running with sudo
        try:
            from os import chown
            from pwd import getpwnam

            user_info = getpwnam(USER)
            chown(str(LOCKFILE_PATH), user_info.pw_uid, user_info.pw_gid)
        except (ImportError, KeyError, PermissionError):
            pass  # silently fail if we can't change ownership

        return written


@dataclass
class File:
    """a file with metadata"""

    path: Path

    mtime: float = 0.0
    hash: str = ""
    corresponding_git_hash: str = ""

    locked_mtime: float = 0
    locked_hash: str = ""
    locked_corresponding_git_hash: str = ""

    @override
    def __str__(self) -> str:
        """represents the file as a string, in this case, from the file's path field"""
        return str(self.path)

    @override
    def __hash__(self) -> int:
        """for dict support"""
        return hash(self.path)

    @_result_wrap(default="")
    def resolve_hash(self) -> str:
        """
        calculates the hash of the file using whichever hashing tool is
        available, else uses blake2b from python stdlib

        this method can throw exceptions
        """

        if self.hash != "":
            return self.hash

        contents = self.path.read_bytes()
        self.hash = blake2b(contents).hexdigest()

        return self.hash

    @_result_wrap(default=0.0)
    def resolve_mtime(self) -> float:
        """resolves and sets the mtime (modification time) from the file's path"""
        if self.mtime == 0:
            self.mtime = self.path.stat().st_mtime
        return self.mtime

    @_result_wrap(default="")
    def resolve_corresponding_git_hash(
        self,
        dirty_files: list[Path] | None = None,
        current_git_hash: str = "",
    ) -> str:
        """
        files can only resolve its own git hash if
        `str(REPO_ROOT) is in str(self.path)`, and that it is not within the list
        of files produced by `_resolve_dirty_files()`

        satisfaction of that condition asserts that:

        1. the file is within the bounds of the repository
        2. thus purposing it as a a virtual file
        3. and is tracked by repo's vcs

        real files can not have their hashes resolved, and will only be set:

        - during operation of the files set or files sync command
        - when their contents are overwritten or matched with a virtual file
        - of which has a resolvable git hash as long as:
            - the virtual file is not dirty as per the repo root's vcs
        """
        warn(
            "resolve_corresponding_git_hash is not implemented", RuntimeWarning
        )  # TODO
        return self.corresponding_git_hash

    @_result_wrap(default=None)
    def resolve(self) -> None:
        mtime_result = self.resolve_mtime()
        self.mtime = mtime_result.get()

        hash_result = self.resolve_hash()
        self.hash = hash_result.get()

        git_hash_result = self.resolve_corresponding_git_hash()
        self.corresponding_git_hash = git_hash_result.get()

    @_result_wrap(default=_DefaultMSTLockedFileData)
    def dump_single_lock_data(self) -> MSTLockedFileData:
        """dumps the lock data for the file into a single
        MSTLockedFileData-shaped dict"""
        if any([self.mtime == 0, self.hash == "", self.corresponding_git_hash == ""]):
            _ = self.resolve().cry()

        return {
            "mtime": self.mtime,
            "hash": self.hash,
            "corresponding_git_hash": self.corresponding_git_hash,
        }

    def load_single_lock_data(self, data: MSTLockedFileData) -> None:
        """loads the lock data for the file from a single
        MSTLockedFileData-shaped dict"""
        self.locked_mtime = data["mtime"]
        self.locked_hash = data["hash"]
        self.locked_corresponding_git_hash = data["corresponding_git_hash"]

    def load_from_lockfile(self, lockfile: MSTLockfile) -> None:
        """
        loads the lock data for the file from a MSTLockfile-shaped dict
        holding multiple MSTLockedFileData-shaped dict values
        """
        if self.path not in lockfile:
            raise KeyError(f"file `{self.path}` not found in lockfile")
        self.load_single_lock_data(lockfile[self.path])


class MSTFileManager:
    virt_real_mapping: dict[File, File] = {}

    @staticmethod
    def _iterate_virtual_repo_root() -> Generator[Path, None, None]:
        """
        iterates over all relevant files in the repository based on platform

        filters out directories, top level files, top level .* directories,
        and applies platform-specific filtering

        returns: `Generator[Path, None, None]`
            generator yielding Path objects for each relevant repository file
        """
        heart_dir_str = str(REPO_ROOT.joinpath("heart"))
        home_dir_str = str(REPO_ROOT.joinpath("home"))

        # iterate and filter files
        for file in REPO_ROOT.rglob("*"):
            file_str = str(file)

            # 0. no directories
            if not file.is_file():
                continue

            # 1. no top-level files
            if file.parent == REPO_ROOT:
                continue

            # 2a. no top-level .* files:
            if file_str.startswith(str(REPO_ROOT.joinpath("a"))[:-1] + "."):
                continue

            # 3. no heart directory
            if heart_dir_str in file_str:
                continue

            # 4. platform-specific filtering
            match system():
                case "Linux" | "linux":
                    if DARWIN_SPECIFIC_DIR_STR in file_str:
                        continue
                    if WINDOWS_SPECIFIC_DIR_STR in file_str:
                        continue
                case "Darwin" | "darwin":
                    # darwin/macOS: only care about home and @darwin
                    if not (
                        (DARWIN_SPECIFIC_DIR_STR in file_str)
                        or (home_dir_str in file_str)
                    ):
                        continue
                case "Windows" | "windows":
                    # darwin/macOS: only care about home and @windows
                    if not (
                        (WINDOWS_SPECIFIC_DIR_STR in file_str)
                        or (home_dir_str in file_str)
                    ):
                        continue
                case _:
                    # assume unix-like, ignore @darwin, @windows, @linux
                    if DARWIN_SPECIFIC_DIR_STR in file_str:
                        continue
                    if WINDOWS_SPECIFIC_DIR_STR in file_str:
                        continue
                    if LINUX_SPECIFIC_DIR_STR in file_str:
                        continue

            yield file

    @staticmethod
    def _map_virtual_path(file: Path) -> Path:
        """
        maps a virtual repository file path to its mapped real/target/system location

        applies transformations in order:

        1. ./@<platform>/<file path> -> <prefix>/<file path>
        2. <prefix>/home/<file> -> <prefix>/Users/<username>/<file> (darwin)
                                -> C:\\Users\\<username>\\<file>    (windows)
                                -> <prefix>/home/<username>/<file>  (default)
        3. ./<any other> -> <prefix>/<any other>

        arguments:
            `file: Path`
                path to a file in the repository

        returns: `Path`
            mapped path where the file should be placed on the system
        """
        file_str = str(file)

        # 1. fix up platform-specific directories
        if file_str.startswith(DARWIN_SPECIFIC_DIR_STR):
            file_str = file_str.replace(DARWIN_SPECIFIC_DIR_STR + "/", f"{PREFIX}")
        elif file_str.startswith(LINUX_SPECIFIC_DIR_STR):
            file_str = file_str.replace(LINUX_SPECIFIC_DIR_STR + "/", f"{PREFIX}")
        elif file_str.startswith(WINDOWS_SPECIFIC_DIR_STR):
            file_str = file_str.replace(WINDOWS_SPECIFIC_DIR_STR + "\\", f"{PREFIX}")
        else:
            file_str = file_str.replace(str(REPO_ROOT) + SLASH, f"{PREFIX}")

        # 2. fix up user-unspecific home directories to the users actual home directory
        if file_str.startswith(prefixed_home := f"{PREFIX}home"):
            actual_home: str = ""
            match system():
                case "Darwin":
                    actual_home = f"{PREFIX}Users/{USER}"
                case "Windows":
                    actual_home = f"{PREFIX}Users\\{USER}"
                case _:
                    actual_home = f"{PREFIX}home/{USER}"

            # 5. fix user-unspecific home directories to the users actual home directory
            if file_str.startswith(prefixed_home):
                file_str = file_str.replace(prefixed_home, actual_home)

        return Path(file_str)

    def __init__(self) -> None:
        for virt_file in self._iterate_virtual_repo_root():
            self.virt_real_mapping[File(virt_file)] = File(
                self._map_virtual_path(virt_file)
            )


def files__set() -> int:
    """
    copies all virtual repository files to their mapped real system
    locations

    iterates through all relevant files and writes them to their mapped
    target locations, creating parent directories as needed

    no actual actions are performed,
    pass in "--yes" if you're okay with the changes
    """
    print(
        f" -> user is {USER}",
        f" -> prefix is '{PREFIX}'\n",
        sep="\n",
    )

    errors: list[tuple[Path, Path, str]] = []
    files = MSTFileManager()

    for virt_file, real_file in files.virt_real_mapping.items():
        virt_file_path, real_file_path = virt_file.path, real_file.path

        if "--yes" not in orig_argv:
            print(
                " ...",
                real_file_path,
                "(skipped)",
            )
            continue

        try:
            # check parent directory permissions
            if not real_file_path.parent.exists():
                # find the first existing parent to check write permissions
                parent = real_file_path.parent
                while not parent.exists() and parent != parent.parent:
                    parent = parent.parent

                if not access(parent, W_OK):
                    raise PermissionError(f"no write permission for {parent}")

                makedirs(real_file_path.parent, exist_ok=True)  # mkdir -p

            elif not access(real_file_path.parent, W_OK):
                raise PermissionError(
                    f"no write permission for {real_file_path.parent}"
                )

            # check if file exists and is writable
            if real_file_path.exists() and not access(real_file_path, W_OK):
                raise PermissionError(f"no write permission for {real_file_path}")

            content = virt_file_path.read_bytes()
            _ = real_file_path.write_bytes(content)
            print(" >>>", real_file_path, "(ok)")

        except Exception as exc:
            print(" !!!", real_file_path, f"(error: {exc})")
            errors.append((virt_file_path, real_file_path, str(exc)))

    # summary
    if errors:
        print(f"\nfound {len(errors)} error(s) while setting files:")
        for repo_file, real_file_path, reason in errors:
            print(f"  - {repo_file.relative_to(REPO_ROOT)} ({reason})")
    else:
        print("\nall files set successfully!")

    return len(errors)


def files__add() -> int:
    print("\nerror: not implemented")
    return 1


def files__remove() -> int:
    print("\nerror: not implemented")
    return 1


def files__rm() -> int:
    return files__remove()


def files__del() -> int:
    return files__remove()


def files__delete() -> int:
    return files__remove()


def files__list() -> int:
    """lists all files and their mappings, similar to `ls`"""
    print(f" -> user is {USER}", f" -> prefix is '{PREFIX}'\n", sep="\n")

    files = MSTFileManager()
    for virt_file, real_file in files.virt_real_mapping.items():
        print(f"{virt_file.path.relative_to(REPO_ROOT)} -> {real_file}")

    return 0


def files__ls() -> int:
    return files__list()


def files__status() -> int:
    """
    usage: status [-l] [-a]

      -l  for long output with detailed mtime and hash information
      -a  for output all files as they are processed

    compares virtual repository files against their mapped real system
    locations, similar to `git status`

    uses the last known file modification times in the lockfile to see
    which files have changed, then resolving current hashes for files
    that may have changed, comparing virtual vs real file contents

    output prefixes:
      ...  files are in sync or skipped
      !!!  files have different content (hash mismatch)
      ???  errors occurred (permission denied, missing files, read errors)

    note: some system files may require sudo to read
    """

    files = MSTFileManager()
    output_long = any(["-l" in orig_argv, "-al" in orig_argv, "-la" in orig_argv])
    output_all_files = any(["-a" in orig_argv, "-al" in orig_argv, "-la" in orig_argv])

    print(f"-> prefix is '{PREFIX}'")

    # load and validate lockfile
    try:
        lockfile = MSTLockfile.load_from_repo()
        print("-> read lockfile successfully")

    except FileNotFoundError:
        print(
            "\nerror: the lockfile is missing, or is not up to date\n"
            + f"please run `{orig_argv[0]} {orig_argv[1]} files lock`"
        )
        return 1

    except (ValueError, KeyError) as e:
        print(
            f"\nerror: lockfile is malformed: {e}\n"
            + f"please run `{orig_argv[0]} {orig_argv[1]} files lock`"
        )
        return 1

    # check if lockfile has all expected files
    for virt_file, real_file in files.virt_real_mapping.items():
        if virt_file.path not in lockfile or real_file.path not in lockfile:
            print(
                "\nerror: the lockfile is missing, or is not up to date\n"
                + f"please run `{orig_argv[0]} {orig_argv[1]} files lock`"
            )
            return 1

    # load locked data and resolve mtimes/hashes, collecting errors
    file_errors: dict[tuple[File, File], str] = {}  # maps (virt, real) -> error_msg

    for virt_file, real_file in files.virt_real_mapping.items():
        virt_file.load_from_lockfile(lockfile)
        real_file.load_from_lockfile(lockfile)

        # resolve virtual file mtime and hash
        virt_mtime_result = virt_file.resolve_mtime()
        if not virt_mtime_result:
            file_errors[(virt_file, real_file)] = "could not get virtual file mtime"
            continue

        virt_hash_result = virt_file.resolve_hash()
        if not virt_hash_result:
            file_errors[(virt_file, real_file)] = "could not read and hash virtual file"
            continue

        # check if real file exists
        if not real_file.path.exists():
            file_errors[(virt_file, real_file)] = "real file is missing"
            continue

        # resolve real file mtime and hash
        real_mtime_result = real_file.resolve_mtime()
        if not real_mtime_result:
            file_errors[(virt_file, real_file)] = "could not get real file mtime"
            continue

        real_hash_result = real_file.resolve_hash()
        if not real_hash_result:
            file_errors[(virt_file, real_file)] = "could not read and hash real file"
            continue

        # no errors, mark as processed
        file_errors[(virt_file, real_file)] = ""

    print("-> resolved mtimes and hashes\n")

    # corroborate findings: compare hashes and collect differing files
    differing_files: list[tuple[File, File, str]] = []
    for (virt_file, real_file), error_msg in file_errors.items():
        virt_path_str = str(virt_file.path.relative_to(REPO_ROOT))

        if error_msg:
            # there was an error during processing
            differing_files.append((virt_file, real_file, error_msg))
            if output_all_files:
                print(f" ??? {virt_path_str} -> {real_file.path} (error: {error_msg})")
        elif virt_file.hash != real_file.hash:
            # hashes differ
            differing_files.append((virt_file, real_file, ""))
            if output_all_files:
                print(f" !!! {virt_path_str} -> {real_file.path} (different)")
        elif output_all_files:
            # files are the same
            print(f" ... {virt_path_str} -> {real_file.path} (same)")

    # output results
    if not differing_files:
        if output_long:
            print()
            for virt_file, real_file in files.virt_real_mapping.items():
                virt_path_str = str(virt_file.path).replace(str(REPO_ROOT) + SLASH, "")
                print(f" ... {virt_path_str} -> {real_file.path}")
            print("\nall files in sync")
        else:
            print("\nall files in sync")
        return 0

    if output_all_files and output_long:
        print()

    # show differing files
    if output_long:
        print(f"there are {len(differing_files)} file(s) differing:\n")

        for virt_file, real_file, error_msg in differing_files:
            virt_path_str = str(virt_file.path).replace(str(REPO_ROOT) + SLASH, "")

            if error_msg:
                print(f" ??? {virt_path_str} -> {real_file.path} ({error_msg})")

            else:
                print(f" <-- {virt_path_str}")
                if virt_file.mtime != 0:
                    dt = datetime.fromtimestamp(virt_file.mtime)
                    print(f"     ... mtime : {dt.strftime('%B %d, %Y %H:%M:%S')}")
                if virt_file.hash != "":
                    print(f"     ... hash  : {virt_file.hash[:16]}")

                print(f" --> {real_file.path}")
                if real_file.mtime != 0:
                    dt = datetime.fromtimestamp(real_file.mtime)
                    print(f"     ... mtime : {dt.strftime('%B %d, %Y %H:%M:%S')}")
                if real_file.hash != "":
                    print(f"     ... hash  : {real_file.hash[:16]}")

    else:
        for virt_file, real_file, error_msg in differing_files:
            virt_path_str = str(virt_file.path).replace(str(REPO_ROOT) + SLASH, "")
            if error_msg:
                print(f" ??? {virt_path_str} -> {real_file.path}")
            else:
                print(f" !!! {virt_path_str} -> {real_file.path}")
        print(f"\nthere are {len(differing_files)} file(s) differing")

    return 0


def files__lock() -> int:
    f"""forcefully creates a lockfile at `{LOCKFILE_PATH}`"""
    files = MSTFileManager()
    lockfile = MSTLockfile()

    for virt_file, real_file in files.virt_real_mapping.items():
        lockfile[virt_file.path] = virt_file.dump_single_lock_data().get()
        lockfile[real_file.path] = real_file.dump_single_lock_data().get()

    written = lockfile.dump_to_repo()
    print("\nupdated lockfile!")
    return written


def files__sync() -> int:
    print("\nerror: not implemented")
    return 1


def meta__update_readme() -> int:
    """
    reads in the README.md from the repo root, replaces the first multiline
    code block with the output of `tree . -aA --gitignore -I ".git/|.*/"`

    uses `nix run nixpkgs.tree` if tree is not installed but nix is
    """

    readme_path = REPO_ROOT.joinpath("README.md")
    if not readme_path.exists():
        print("\nerror: README.md not found", file=stderr)
        return 1

    # determine which tree command to use
    tree_cmd: list[str] = []
    if which("tree"):
        tree_cmd = ["tree"]
    elif which("nix"):
        tree_cmd = [
            "nix",
            "run",
            "nixpkgs#tree",
            "--",
        ]
    else:
        print("\nerror: neither tree nor nix command found", file=stderr)
        return 1

    tree_cmd += [".", "-an", "--gitignore", "-I", ".git/|.*/"]
    print(f" -> command is `{' '.join(tree_cmd)}`")

    # run tree command
    try:
        result: CompletedProcess[str] = run(
            tree_cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
            encoding="utf-8",
        )

        tree_lines = (
            # replace U+A0 with space (output quirk of tree)
            result.stdout.replace(chr(160), " ")
        ).splitlines()

        # remove the last line (summary like "15 directories, 29 files")
        if tree_lines and ("director" in tree_lines[-1] or "file" in tree_lines[-1]):
            tree_lines = tree_lines[:-1]

        # remove trailing empty lines
        while tree_lines and not tree_lines[-1].strip():
            _ = tree_lines.pop()

    except Exception as exc:
        print(f"\nerror: tree command failed: {exc}", file=stderr)
        return 1

    # read README.md for first and second ``` markers
    readme_lines: list[str] = readme_path.read_text().splitlines(keepends=True)
    first_backtick_idx: int | None = None
    second_backtick_idx: int | None = None

    for i, line in enumerate(readme_lines):
        if line.strip().startswith("```"):
            if first_backtick_idx is None:
                first_backtick_idx = i
            elif second_backtick_idx is None:
                second_backtick_idx = i
                break

    if (first_backtick_idx is None) or (second_backtick_idx is None):
        print("\nerror: could not find code block delimiters in README.md", file=stderr)
        return 1

    # build new readme
    new_readme_lines: list[str] = []
    new_readme_lines.extend(readme_lines[: first_backtick_idx + 1])
    new_readme_lines.extend([(line + "\n") for line in tree_lines])
    new_readme_lines.extend(readme_lines[second_backtick_idx:])

    try:
        lines_written = readme_path.write_text("".join(new_readme_lines))
        print(f" -> wrote {lines_written} characters to README.md")
    except Exception as e:
        print(f"\nerror: failed to update README.md: {e}", file=stderr)
        return 1

    print("\nsuccessfully updated readme!")
    return 0


def install() -> int:
    """
    usage: install [command_name]

    adds a small runner script to `~/.local/bin`

    defaults <command_name> to `mst`
    """
    install_command_name: str = orig_argv[3] if len(orig_argv) > 3 else "mst"
    print(f" -> will be installed as `{install_command_name}`")

    if which(install_command_name):
        print(f"\nerror: command `{install_command_name}` already exists", file=stderr)
        return 1

    local_bin_path: Path = Path.home().joinpath(".local/bin")
    print(f" -> ensuring `{local_bin_path}` exists")
    try:
        local_bin_path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(
            f"\nerror: failed to create `{local_bin_path}` directory: {exc}",
            file=stderr,
        )
        return 1

    # create the runner script
    runner_script_path: Path = local_bin_path.joinpath(install_command_name)
    runner_script_content: str = ""
    if system() == "Windows":
        runner_script_content = (
            f'@echo off\n"{executable}" "{REPO_ROOT.joinpath("tooling.py")}" %*\n'
        )
        runner_script_path = runner_script_path.with_suffix(".bat")
    else:
        runner_script_content = f'#!/bin/sh\nexec "{executable}" "{REPO_ROOT.joinpath("tooling.py")}" "$@"\n'

    # write the script
    try:
        _ = runner_script_path.write_text(runner_script_content, encoding="utf-8")
        print(f" -> wrote runner script to {runner_script_path}")

    except Exception as exc:
        print(f"\nerror: failed to write to `{runner_script_path}`: {exc}", file=stderr)
        return 1

    # make executable on non-windows systems
    if system() != "Windows":
        try:
            chmod(runner_script_path, 0o755)
            print(f" -> make `{runner_script_path}` executable")
        except Exception as e:
            print(
                f"\nerror: failed to make `{runner_script_path}` executable: {e}",
                file=stderr,
            )
            return 1

    # check if .local/bin is in PATH
    path_env = getenv("PATH", "")
    local_bin_str = str(local_bin_path)
    is_in_path = local_bin_str in path_env.split(":" if system() != "Windows" else ";")

    print(f"\nsuccessfully installed `{install_command_name}` to {runner_script_path}")
    if is_in_path:
        print(f"you can now run `{install_command_name}` from anywhere")
    else:
        print(
            f" ... warning: `{local_bin_path}` is not in your PATH variable!"
            + " after adding to PATH, restart your shell, editor,"
            + " or source your rc/profile file!"
        )

    return 0


def main() -> int:
    """command line entry point"""

    subcommand_mappings: dict[str, dict[str, Callable[[], int]]] = {}

    # dynamically list all subcommand functions
    for key, value in globals().items():  # pyright: ignore[reportAny]
        if callable(value) and value.__module__ == __name__:  # pyright: ignore[reportAny]
            if key.startswith("_"):  # private functions
                continue
            if key[0].isupper():  # classes
                continue
            if key == "main":  # this function
                continue

            subcommand_group: str = "_default"
            subcommand_name: str = key
            if "__" in key:
                subcommand_group, subcommand_name = key.split("__")

            subcommand_name = subcommand_name.replace("_", "-")

            # verify function signature matches Callable[[], int]
            try:
                sig = signature(value)
                if (len(sig.parameters) == 0) and sig.return_annotation is not int:  # pyright: ignore[reportAny]
                    continue

                if subcommand_group not in subcommand_mappings:
                    subcommand_mappings[subcommand_group] = {}

                subcommand_mappings[subcommand_group][subcommand_name] = cast(
                    Callable[[], int], value
                )

            # skip if we can't
            except (ValueError, TypeError):
                continue

    if (
        (len(orig_argv) >= 4)
        and (orig_argv[2] in subcommand_mappings)
        and (orig_argv[3] in subcommand_mappings[orig_argv[2]])
    ):
        subcommand_group = orig_argv[2]
        subcommand_name = orig_argv[3]

        print(f"mark's system tooling \\ {subcommand_group} \\ {subcommand_name}")
        return subcommand_mappings[subcommand_group][subcommand_name]()

    if (len(orig_argv) >= 3) and (
        orig_argv[2] in subcommand_mappings.get("_default", {})
    ):
        subcommand_group = "_default"
        subcommand_name = orig_argv[2]

        print(f"mark's system tooling \\ {subcommand_name}")
        return subcommand_mappings[subcommand_group][subcommand_name]()

    else:
        # build help message
        print(
            f"usage: {orig_argv[0]} {orig_argv[1]} [subcommand_group] subcommand_name"
        )
        print("\ncommands:")
        for subcommand_group in subcommand_mappings.keys():
            for subcommand_name in subcommand_mappings[subcommand_group].keys():
                if not isinstance(
                    docstring := subcommand_mappings[subcommand_group][
                        subcommand_name
                    ].__doc__,
                    str,
                ):
                    continue

                print(
                    f"    {subcommand_group} {subcommand_name}"
                    if subcommand_group != "_default"
                    else f"    {subcommand_name}"
                )

                for line in docstring.strip().splitlines():
                    print(f"    ... {line.lstrip()}")
                print()

        return -1


if __name__ == "__main__":
    exit(main())
