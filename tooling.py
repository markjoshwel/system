#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# ///
"""mark's system tooling: cross-platform system and user configuration file manager"""

from collections.abc import Generator
from dataclasses import dataclass
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
from sys import executable, orig_argv, stderr, version_info
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
USER: Final[str] = getenv("MST_USER", getlogin())
_WINDOWS_SYSTEM_ROOT = expandvars("%SystemRoot%")
PREFIX: Final[str] = getenv(
    key="MST_PREFIX",
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
PathsWithMessages = dict[Path, str]
FilesWithMessages = dict["File", str]


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


def _p(n: int, word: str) -> str:
    """pluraliser for info/error messages"""
    return (word + "s") if (n > 1) else word


class RepositoryFileState(NamedTuple):
    """
    attributes:
        `git_hash: str`
            git hash of latest/current commit
        `tracked_files: list[Path]`
            list of tracked files in the repository
        `modified_files: list[Path]`
            any tracked files with changes (staged, unstaged, etc) not yet committed
        `untracked_files: list[Path]`
            list of untracked files in the repository
    """

    git_hash: str
    tracked_files: list[Path]
    dirty_files: list[Path]
    untracked_files: list[Path]

    @classmethod
    def from_repo(cls, repo: Path = REPO_ROOT) -> Result["RepositoryFileState"]:
        try:
            # get current git commit hash
            hash_result = run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            )
            current_git_hash = hash_result.stdout.strip()

            # get tracked files
            tracked_result = run(
                ["git", "ls-files"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            )
            tracked_files = [
                repo.joinpath(line.strip())
                for line in tracked_result.stdout.strip().split("\n")
                if line.strip()
            ]

            # get status for modified and untracked files
            status_result = run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            )

            dirty_files: list[Path] = []
            untracked_files: list[Path] = []

            for line in status_result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                
                status_code, _file_path = line.split(maxsplit=1)
                file_path = REPO_ROOT.joinpath(_file_path)
                # assert file_path.exists(), f"{file_path}"

                # check if file is untracked
                if status_code.startswith("??"):
                    untracked_files.append(file_path)
                # any other status code means it's a tracked file with modifications
                else:
                    dirty_files.append(file_path)

            return Result(
                value=cls(
                    git_hash=current_git_hash,
                    tracked_files=tracked_files,
                    dirty_files=dirty_files,
                    untracked_files=untracked_files,
                ),
                error=None,
            )

        except Exception as e:
            return Result(
                value=cls(
                    git_hash="",
                    tracked_files=[],
                    dirty_files=[],
                    untracked_files=[],
                ),
                error=e,
            )


def meta__rfs_test() -> int:
    repofs = RepositoryFileState.from_repo().get()
    print("RepositoryFileState(")
    print(f"    git_hash={repofs.git_hash!r},")
    print("    tracked_files=[")
    for file_path in repofs.tracked_files:
        print(f"        {file_path!r},")
    print("    ],")
    print("    dirty_files=[")
    for file_path in repofs.dirty_files:
        print(f"        {file_path!r},")
    print("    ],")
    print("    untracked_files=[")
    for file_path in repofs.untracked_files:
        print(f"        {file_path!r},")
    print("    ],")
    print(")")
    return 0


class MSTLockedFileData(TypedDict):
    mtime: float
    checksum: str
    corresponding_git_hash: str


_DefaultMSTLockedFileData = MSTLockedFileData(
    mtime=0.0,
    checksum="",
    corresponding_git_hash="",
)

MSTLockfileDictType = dict[Path, MSTLockedFileData]


class MSTLockfileVerificationResult(NamedTuple):
    dangling: PathsWithMessages = {}
    missing: PathsWithMessages = {}
    unresolved: PathsWithMessages = {}


class MSTLockfile(MSTLockfileDictType):
    """
    lockfile dictionary with methods for loading, dumping (serdes),
    checking, and maintaining the lockfile
    """

    def prune_dangling_entries(self) -> MSTLockfileDictType:
        """remove MSTLockedFileData entries for non-existent files"""
        pruned_entries: MSTLockfileDictType = {}

        for key in list(self.keys()):
            try:
                if key.exists() and key.is_file():
                    continue
            except Exception:
                continue

            pruned_entries[key] = self[key]
            del self[key]

        return pruned_entries

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
                for key in ("mtime", "checksum", "corresponding_git_hash")
            ):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, missing any of the following keys: 'mtime', 'checksum', 'corresponding_git_hash'"
                )
            if not isinstance(supposedly_lockedfiledata["mtime"], float):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, 'mtime' is not a float"
                )
            if not isinstance(supposedly_lockedfiledata["checksum"], str):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, 'checksum' is not a string"
                )
            if not isinstance(supposedly_lockedfiledata["corresponding_git_hash"], str):
                raise ValueError(
                    f"invalid lockfile data for {key_path}, 'corresponding_git_hash' is not a string"
                )

        lockfile: MSTLockfile = cls()
        for key_str, value in lockfile_dict.items():  # pyright: ignore[reportUnknownVariableType]
            lockfile[Path(key_str)] = cast(MSTLockedFileData, value)  # pyright: ignore[reportUnknownArgumentType]

        return lockfile

    def dumps_json(self, indent: int = 2) -> str:
        """serialise the MSTLockfile object into a json string"""
        return dumps(
            {
                str(lock_path).replace(SLASH, "/"): lock_data
                for lock_path, lock_data in self.items()
            },
            indent=indent,
        )

    @classmethod
    def load_from_repo(
        cls,
        prune_dangling_entries: bool = True,
    ) -> tuple["MSTLockfile", MSTLockfileDictType]:
        """
        loads the MSTLockfile object from the repository,
        returns the a Result[MSTLockfile] object
        """
        if not LOCKFILE_PATH.exists():
            raise FileNotFoundError("lockfile not found")
        if not LOCKFILE_PATH.is_file():
            raise FileNotFoundError("lockfile is not a file")

        lockfile_text = LOCKFILE_PATH.read_text(encoding="utf-8")
        lockfile = cls.loads_json(lockfile_text)

        pruned: MSTLockfileDictType = {}
        if prune_dangling_entries:
            pruned = lockfile.prune_dangling_entries()

        return lockfile, pruned

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
                "# Automatically created by mark's system tooling\n*\n",
                encoding="utf-8",
            )

        written = LOCKFILE_PATH.write_text(self.dumps_json(), encoding="utf-8")

        # ensure lockfile is owned by the actual user, not root if running with sudo
        try:
            from os import chown
            from pwd import getpwnam

            user_info = getpwnam(USER)
            chown(str(LOCKFILE_PATH), user_info.pw_uid, user_info.pw_gid)
            chown(
                str(LOCKFILE_PATH.parent.joinpath(".gitignore")),
                user_info.pw_uid,
                user_info.pw_gid,
            )
            chown(str(LOCKFILE_PATH.parent), user_info.pw_uid, user_info.pw_gid)

        except (ImportError, KeyError, PermissionError):
            print("warning: failed to change ownership of lockfile", file=stderr)

        return written

    @_result_wrap(default=MSTLockfileVerificationResult())
    def verify(
        self,
        files: list["File"],
    ) -> MSTLockfileVerificationResult:
        """
        verifies that:

        1. there are no dangling entries
        2. all given files are in the lockfile

        returns: `tuple[list[str], list[str], list[str]]`
            list of dangling, missing and unresolved entry messages
        """
        results = MSTLockfileVerificationResult()

        # 1. verify that there are no dangling entries
        removed_entries = self.prune_dangling_entries()
        if removed_entries:
            for file_path, _ in removed_entries.items():
                results.dangling[file_path] = f"pruned dangling entry for '{file_path}'"

        # 2. verify that all given files are in the lockfile
        for file in files:
            if file.path not in self:
                results.missing[file.path] = f"missing entry for '{file}'"

        # 3. verify that all lockfile entries have no missing data
        for file_path, entry in self.items():
            if "mtime" not in entry:
                results.unresolved[file_path] = f"missing 'mtime' for '{file_path}'"
            elif entry["mtime"] == 0.0:
                results.unresolved[file_path] = f"unresolved 'mtime' for '{file_path}'"

            if "checksum" not in entry:
                results.unresolved[file_path] = f"missing 'checksum' for '{file_path}'"
            elif entry["checksum"] == "":
                results.unresolved[file_path] = (
                    f"unresolved 'checksum' for '{file_path}'"
                )

            if "corresponding_git_hash" not in entry:
                results.unresolved[file_path] = (
                    f"missing 'corresponding_git_hash' for '{file_path}'"
                )
            elif entry["corresponding_git_hash"] == "":
                results.unresolved[file_path] = (
                    f"unresolved 'corresponding_git_hash' for '{file_path}'"
                )

        return results


@dataclass
class File:
    """a file with metadata"""

    path: Path

    mtime: float = 0.0
    checksum: str = ""
    corresponding_git_hash: str = ""

    locked_mtime: float = 0
    locked_checksum: str = ""
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
    def resolve_checksum(self) -> str:
        """calculates the blake2b checksum of the file"""

        if self.checksum != "":
            return self.checksum

        contents = self.path.read_bytes()
        self.checksum = blake2b(contents).hexdigest()

        return self.checksum

    @_result_wrap(default=0.0)
    def resolve_mtime(self) -> float:
        """resolves and sets the mtime (modification time) from the file's path"""
        if self.mtime == 0.0:
            self.mtime = self.path.stat().st_mtime
        return self.mtime

    @_result_wrap(default="")
    def resolve_corresponding_git_hash(
        self,
        repofs: RepositoryFileState | None = None,
    ) -> str:
        """
        files can only resolve its own git hash if in the repository,
        and that it is not dirty

        satisfaction of that condition asserts that:

        1. the file is within the bounds of the repository
        2. thus purposing it as a a virtual file
        3. and is tracked by repo's vcs

        real files can not have their hashes resolved, and will only be set
        during the operation of `files sync` or `files set`
        """

        if str(REPO_ROOT) not in str(self.path):
            self.corresponding_git_hash = ""
            return self.corresponding_git_hash

        if repofs is None:
            repofs = RepositoryFileState.from_repo().get()

        if self.path in repofs.tracked_files:
            self.corresponding_git_hash = repofs.git_hash

        if self.path in repofs.untracked_files:
            raise Exception(
                f"file '{self.path}' is untracked, add and commit it to the repository"
            )

        if self.path in repofs.dirty_files:
            raise Exception(
                f"file '{self.path}' is dirty, commit its changes to the repository"
            )
        
        # debugging lol
        # print(
        #     f"\n\t'{self.path}'"
        #     + f"\n\t ... {str(REPO_ROOT) in str(self.path)=}"
        #     + f"\n\t ... {self.path in repofs.tracked_files=}"
        #     + f"\n\t ... {self.path in repofs.dirty_files=}"
        #     + f"\n\t ... {self.path in repofs.untracked_files=}"
        # )

        return self.corresponding_git_hash

    @_result_wrap(default=None)
    def resolve(self, repofs: RepositoryFileState | None = None) -> None:
        _ = self.resolve_mtime().get()
        _ = self.resolve_checksum().get()
        _ = self.resolve_corresponding_git_hash(repofs).get()

    @_result_wrap(default=_DefaultMSTLockedFileData)
    def dump_single_lock_data(self, repofs: RepositoryFileState | None = None) -> MSTLockedFileData:
        """dumps the lock data for the file into a single
        MSTLockedFileData-shaped dict"""
        _ = self.resolve(repofs).cry()

        return MSTLockedFileData(
            mtime=self.mtime,
            checksum=self.checksum,
            corresponding_git_hash=self.corresponding_git_hash,
        )

    def load_single_lock_data(self, data: MSTLockedFileData, safe: bool = True) -> None:
        """loads the lock data for the file from a single
        MSTLockedFileData-shaped dict"""
        if safe:
            self.locked_mtime = data.get("mtime", 0.0)
            self.locked_checksum = data.get("checksum", "")
            self.locked_corresponding_git_hash = data.get("corresponding_git_hash", "")
        else:
            self.locked_mtime = data["mtime"]
            self.locked_checksum = data["checksum"]
            self.locked_corresponding_git_hash = data["corresponding_git_hash"]

    def load_from_lockfile(self, lockfile: MSTLockfile, fail: bool = True) -> None:
        """
        loads the lock data for the file from a MSTLockfile-shaped dict
        holding multiple MSTLockedFileData-shaped dict values
        """
        if self.path not in lockfile:
            if fail:
                raise KeyError(f"file `{self.path}` not found in lockfile")
            else:
                return
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

    @_result_wrap(default=FilesWithMessages())
    def mass_resolve_corresponding_git_hashes(self, repofs: RepositoryFileState) -> FilesWithMessages:
        errors: FilesWithMessages = {}

        for virt_file in self.virt_real_mapping:
            if not (result := virt_file.resolve_corresponding_git_hash(repofs)):
                errors[virt_file] = result.cry(string=True)

        return errors

    def as_list(self) -> list[File]:
        """returns a list of all virtual and real files"""
        _list: list[File] = []
        for virt_file, real_file in self.virt_real_mapping.items():
            _list.append(virt_file)
            _list.append(real_file)
        return _list


# TODO: allow setting files individually
def files__set() -> int:
    """
    usage: files set [target ...]
    
    target can be a path or a glob pattern, omit to set all files
    
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
        file=stderr,
    )

    files = MSTFileManager()
    
    lockfile = MSTLockfile()
    if (LOCKFILE_PATH.exists() and LOCKFILE_PATH.is_file()):
        lockfile, _ = MSTLockfile.load_from_repo()
    
    repofs: RepositoryFileState | None = None
    try:
        repofs = RepositoryFileState.from_repo().get()
    except Exception as exc:
        print(f"warning: could not load repository file state: {exc} ({exc.__class__.__name__})", file=stderr)

    errors: list[tuple[Path, Path, str]] = []
    files_set: int = 0
    
    target_string_list: list[str] = [f for f in orig_argv[4:] if not f.startswith("-")] if len(orig_argv) > 4 else []  # TODO
    target_path_list: list[Path] = []
    target_potential_glob_list: list[str] = []
    
    if target_string_list:
        for target_str in target_string_list:
            target_path = Path(target_str)
            if target_path.exists():
                target_path_list.append(target_path.resolve())
            else:
                target_potential_glob_list.append(target_str)

    for virt_file, real_file in files.virt_real_mapping.items():
        virt_file_path, real_file_path = virt_file.path, real_file.path
        
        is_target: bool = False if target_string_list else True
        if target_string_list:
            for target_path in target_path_list:
                if virt_file_path.resolve() == target_path.resolve():
                    is_target = True
                    break
            
            for target_glob in target_potential_glob_list:
                if virt_file_path.full_match(target_glob):
                    is_target = True
                    break
        
        if not is_target:
            continue

        if "--yes" not in orig_argv:
            print(
                f" ... {virt_file_path.relative_to(REPO_ROOT)} -> {real_file_path} (skipped)",
                file=stderr,
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

            # set file content
            content = virt_file_path.read_bytes()
            _ = real_file_path.write_bytes(content)
            files_set += 1

        except Exception as exc:
            print(f" !!! {virt_file_path.relative_to(REPO_ROOT)} -> {real_file_path} (error: {exc})", file=stderr)
            errors.append((virt_file_path, real_file_path, str(exc)))
        
        print(f" >>> {virt_file_path.relative_to(REPO_ROOT)} -> {real_file_path} (ok)", file=stderr)
        
        # update lockfile
        # try:
        #     virt_file.load_from_lockfile(lockfile)
        #     virt_file_is_unmodified = ((virt_file.locked_mtime != 0.0) and (virt_file.resolve_mtime().get() == virt_file.locked_mtime))
        #     if virt_file_is_unmodified and (repofs is not None):
        #         virt_file_virt_file.resolve_corresponding_git_hash(repofs).get()
        # except Exception as exc:
        #     errors.append((real_file_path, real_file_path, str(exc)))

    # summary
    if errors:
        print(
            f"\nfound {len(errors)} {_p(len(errors), 'error')} while setting files:",
            file=stderr,
        )
        for virt_file_path, real_file_path, reason in errors:
            if virt_file_path == real_file_path:
                print(f"   - {virt_file_path.relative_to(REPO_ROOT)} ({reason})", file=stderr)
            else:
                print(f"   - {virt_file_path.relative_to(REPO_ROOT)} -> {real_file_path} ({reason})", file=stderr)
    
    elif files_set == 0:
        print("\nno files set")
    
    else:
        print("\nall files set successfully!")

    return len(errors)


def files__list() -> int:
    """lists all files and their mappings, similar to `ls`"""
    print(f" -> user is {USER}", f" -> prefix is '{PREFIX}'\n", sep="\n", file=stderr)

    files = MSTFileManager()
    for virt_file, real_file in files.virt_real_mapping.items():
        print(f"{virt_file.path.relative_to(REPO_ROOT)} -> {real_file}")

    return 0


def files__ls() -> int:
    return files__list()


def files__status() -> int:
    """
    usage: status [-a]

    -a  to output all files as they are processed

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

    print(f"-> prefix is '{PREFIX}'", file=stderr)

    # 1. load and init everything

    files = MSTFileManager()
    output_all_files = "-a" in orig_argv

    try:
        lockfile, pruned = MSTLockfile.load_from_repo()
        print("-> loaded lockfile", file=stderr)
        for entry in pruned:
            print(f"   ... pruned dangling entry for '{entry}'", file=stderr)

    except Exception as exc:
        print(
            f"\nerror: lockfile could not be loaded ({exc.__class__.__name__}: {exc})",
            f"run `{orig_argv[0]} {orig_argv[1]} files lock` to generate a new lockfile",
            file=stderr,
            sep="\n",
        )
        return 1

    try:
        if pruned:
            _ = lockfile.dump_to_repo()

    except Exception:
        print("warning: lockfile could not be updated", file=stderr)

    missing_lockfile_entries: list[File] = []
    files_resolution_errors: FilesWithMessages = {}
    files_same: int = 0
    files_different: int = 0
    files_errors: int = 0

    print(file=stderr)
    for virt_file, real_file in files.virt_real_mapping.items():
        for file in (virt_file, real_file):
            file_path_str = (
                str(file.path.relative_to(REPO_ROOT))
                if str(file).startswith(str(REPO_ROOT))
                else str(file)
            )

            # 2. resolve all mtimes

            if file.path not in lockfile:
                missing_lockfile_entries.append(file)
            else:
                file.load_single_lock_data(lockfile[file.path])
                if not (result_mtime := file.resolve_mtime()):
                    files_resolution_errors[file] = (
                        f"could not resolve mtime for '{file_path_str}' ({result_mtime.cry(string=True)})"
                    )

            # 3. if locked mtime and current mtime are different
            #    (file has been modified), resolve hashes

            if (
                # we do not know both the current and previously known mtimes,
                # so fallback to resolving a checksum
                ((not file.mtime) or (not file.locked_mtime))
                or
                # file has been modified, resolve checksum
                (file.mtime != file.locked_mtime)
            ):
                if not (result_virt_checksum := file.resolve_checksum()):
                    files_resolution_errors[file] = (
                        f"could not resolve checksum for '{file_path_str}' ({result_virt_checksum.cry(string=True)})"
                    )

            # file has not been modified, do nothing
            else:
                pass

        # 4. report findings

        if (
            # if both mtimes are present
            (virt_file.mtime and virt_file.locked_mtime)
            and (real_file.mtime and real_file.locked_mtime)
            and
            # and both files have not been modified
            (virt_file.mtime == virt_file.locked_mtime)
            and (real_file.mtime == real_file.locked_mtime)
        ):
            if output_all_files:
                print(
                    f" ... {virt_file.path.relative_to(REPO_ROOT)} -> {real_file} (same)"
                )
            files_same += 1

        # if we can't verify on the surface nothing has changed,
        # then we fallback to checksum resolution
        else:

            def _build_output_str(virt_msg: str = "", real_msg: str = "") -> str:
                error_portion = "error: "
                if virt_msg:
                    error_portion += '"' + virt_msg + '"'
                if real_msg and virt_msg:
                    error_portion += ", "
                if real_msg:
                    error_portion += '"' + real_msg + '"'

                return f" ??? {virt_file.path.relative_to(REPO_ROOT)} -> {real_file} ({error_portion})"

            # but firstly, check if we've already had an issue before
            if (virt_file in files_resolution_errors) or (
                real_file in files_resolution_errors
            ):
                print(
                    _build_output_str(
                        files_resolution_errors.get(virt_file, ""),
                        files_resolution_errors.get(real_file, ""),
                    ),
                    file=stderr,
                )
                files_errors += 1

            else:
                result_virt_checksum = virt_file.resolve_checksum()
                result_real_checksum = real_file.resolve_checksum()

                if (not result_virt_checksum) or (not result_real_checksum):
                    print(
                        _build_output_str(
                            result_virt_checksum.cry(string=True),
                            result_real_checksum.cry(string=True),
                        ),
                        file=stderr,
                    )
                    files_errors += 1

                elif result_virt_checksum.get() == result_real_checksum.get():
                    if output_all_files:
                        print(
                            f" ... {virt_file.path.relative_to(REPO_ROOT)} -> {real_file} (same)"
                        )
                    files_same += 1

                elif result_virt_checksum.get() != result_real_checksum.get():
                    print(
                        f" !!! {virt_file.path.relative_to(REPO_ROOT)} -> {real_file} (different)"
                    )
                    files_different += 1

    if missing_lockfile_entries:
        print(
            f"\nwarning: there are {len(missing_lockfile_entries)} missing lockfile entries",
            f"run `{orig_argv[0]} {orig_argv[1]} files lock` to generate a new lockfile",
            file=stderr,
            sep="\n",
        )

    if files_resolution_errors:
        print(
            f"\nthere were {len(files_resolution_errors)} errors when getting file statuses:",
            file=stderr,
        )
        for file, error in files_resolution_errors.items():
            print(f"   - {file} -> {error}", file=stderr)

    # build final message
    total_files = files_same + files_different + files_errors

    # formatting bullshit
    print(
        "\n" if ((total_files != files_same) or output_all_files) else "",
        end="",
        file=stderr,
    )

    print(
        f"checked {total_files} {_p(total_files, 'file')}",
        f", found {files_same} identical {_p(files_same, 'file')}"
        if files_same
        else "",
        f", found {files_different} different {_p(files_different, 'file')}"
        if files_different
        else "",
        f", encountering {files_errors + len(files_resolution_errors)} {_p(files_same, 'error')}"
        if (files_errors or files_resolution_errors)
        else "",
        ", with 1 warning" if missing_lockfile_entries else "",
        sep="",
    )

    return 0 if not (missing_lockfile_entries or files_resolution_errors) else 1


def files__lock() -> int:
    f"""forcefully creates a lockfile at `{LOCKFILE_PATH}`"""
    files = MSTFileManager()
    repofs = RepositoryFileState.from_repo().get()
    result_hash = files.mass_resolve_corresponding_git_hashes(repofs)

    # there was a critical error resolving git hashes
    if not result_hash:
        print(
            f"\nerror: could not resolve git hashes for repository files ({result_hash.cry(string=True)})"
        )
        return 1

    # there were errors resolving git hashes
    hash_resolution_errors = result_hash.get()
    if hash_resolution_errors:
        print("\nerror: could not resolve some git hashes for repository files")
        for file_path, error in hash_resolution_errors.items():
            print(f" ... {file_path}: {error}")
        return 1

    lockfile = MSTLockfile()
    for virt_file, real_file in files.virt_real_mapping.items():
        lockfile[virt_file.path] = virt_file.dump_single_lock_data(repofs).get()
        lockfile[real_file.path] = real_file.dump_single_lock_data(repofs).get()

    written = lockfile.dump_to_repo()
    print("\nupdated lockfile!")
    return written


def files__sync() -> int:
    files = MSTFileManager()

    try:
        lockfile, _ = MSTLockfile.load_from_repo(prune_dangling_entries=False)
        print(" -> loaded lockfile", file=stderr)

    except Exception as exc:
        print(
            f"\nerror: lockfile could not be loaded ({exc.__class__.__name__}: {exc})",
            f"run `{orig_argv[0]} {orig_argv[1]} files lock` to generate a new lockfile",
            file=stderr,
            sep="\n",
        )
        return 1

    if not (result_verify := lockfile.verify(files=files.as_list())):
        print(
            f"\nerror: lockfile verification failed (error: {result_verify.cry(string=True)})",
            file=stderr,
        )
        return 1

    elif len(result_verify.get().missing) + len(result_verify.get().unresolved):
        real_files: list[Path] = [f.path for f in MSTFileManager.virt_real_mapping.values()]
        real_files_with_corresponding_git_hashes: int = len(real_files)

        print("\nerror: there are errors in the lockfile", file=stderr)
        for _, message in result_verify.get().missing.items():
            print(f" ... {message}", file=stderr)
        for file_path, message in result_verify.get().unresolved.items():
            print(f" ... {message}", file=stderr)
            if file_path in real_files:
                real_files_with_corresponding_git_hashes -= 1

        final_message: str = f"\nrun `{orig_argv[0]} {orig_argv[1]} files lock` to generate a new lockfile"
        
        if real_files_with_corresponding_git_hashes == 0:
            final_message = (
                "\nerror: no real files have corresponding git hashes"
                + f"\nconsider forcefully setting (overriding) all files with `{orig_argv[0]} {orig_argv[1]} files set`"
            )
        
        elif real_files_with_corresponding_git_hashes < len(real_files):
            final_message = (
                "\nerror: some real files are missing corresponding git hashes"
                + f"\nconsider setting (overriding) any differing files with `{orig_argv[0]} {orig_argv[1]} status` and `files set <path/to/file>`"
            )

        print(final_message, file=stderr)

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
    print(f" -> command is `{' '.join(tree_cmd)}`", file=stderr)

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
        print(f" -> wrote {lines_written} characters to README.md", file=stderr)
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
    print(f" -> will be installed as `{install_command_name}`", file=stderr)

    if which(install_command_name):
        print(f"\nerror: command `{install_command_name}` already exists", file=stderr)
        return 1

    local_bin_path: Path = Path.home().joinpath(".local/bin")
    print(f" -> ensuring `{local_bin_path}` exists", file=stderr)
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
        print(f" -> wrote runner script to {runner_script_path}", file=stderr)

    except Exception as exc:
        print(f"\nerror: failed to write to `{runner_script_path}`: {exc}", file=stderr)
        return 1

    # make executable on non-windows systems
    if system() != "Windows":
        try:
            chmod(runner_script_path, 0o755)
            print(f" -> make `{runner_script_path}` executable", file=stderr)
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

    print(
        f"\nsuccessfully installed `{install_command_name}` to {runner_script_path}",
    )
    if is_in_path:
        print(f"you can now run `{install_command_name}` from anywhere")
    else:
        print(
            f" ... warning: `{local_bin_path}` is not in your PATH variable!"
            + " after adding to PATH, restart your shell, editor,"
            + " or source your rc/profile file!",
            file=stderr,
        )

    return 0


def main() -> int:
    """command line entry point"""
    
    # prelude: ensure python 3.13 or higher
    if (version_info < (3, 13)) and ("--idonotcare" not in orig_argv):
        print(
            "error: this script requires python 3.13 or higher (override with `--idonotcare`)",
            file=stderr,
        )
        return 1

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

        print(
            f"mark's system tooling \\ {subcommand_group} \\ {subcommand_name}",
            file=stderr,
        )
        return subcommand_mappings[subcommand_group][subcommand_name]()

    if (len(orig_argv) >= 3) and (
        orig_argv[2] in subcommand_mappings.get("_default", {})
    ):
        subcommand_group = "_default"
        subcommand_name = orig_argv[2]

        print(f"mark's system tooling \\ {subcommand_name}", file=stderr)
        return subcommand_mappings[subcommand_group][subcommand_name]()

    else:
        # build help message
        print(
            f"usage: {orig_argv[0]} {orig_argv[1]} [subcommand_group] subcommand_name",
            file=stderr,
        )
        print("\ncommands:", file=stderr)
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
                    else f"    {subcommand_name}",
                    file=stderr,
                )

                for line in docstring.strip().splitlines():
                    print(f"    ... {line.lstrip()}", file=stderr)
                print(file=stderr)

        return -1


if __name__ == "__main__":
    exit(main())
