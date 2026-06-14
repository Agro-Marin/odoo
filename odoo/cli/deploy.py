import logging
import os
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

import requests

from . import Command

_logger = logging.getLogger(__name__)

# Directory names and file suffixes that should never ship in a module zip.
# VCS metadata can leak credentials; build caches and dependency trees inflate
# uploads 10-100x with no runtime benefit.
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        "CVS",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        ".venv",
        "venv",
        ".env",
        ".idea",
        ".vscode",  # IDE metadata
        "dist",
        "build",  # common build outputs
    }
)
EXCLUDED_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".swp",
        ".swo",
        ".orig",
        ".bak",
        ".DS_Store",
    }
)

# Hosts that deploy treats as local and therefore defaults to http://.
# Exact host match only (substring matches would let 'localhost.evil.com'
# bypass TLS).
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

# (connect, read) timeouts. requests has NO default timeout: without one a
# stuck server hangs the command forever. Connect fails fast; the upload
# read is unbounded because the server installs the module synchronously
# and large modules legitimately take minutes (same rationale as `db load`).
_LOGIN_TIMEOUT = (10, 30)
_UPLOAD_TIMEOUT = (10, None)


def _should_skip(filepath: Path, module_dir: Path) -> bool:
    """Return True if ``filepath`` should be excluded from the deploy zip."""
    # Only the *parent* components are tested against EXCLUDED_DIR_NAMES, never
    # the file's own basename: a legitimate module file named e.g. ``build`` or
    # ``dist`` (no extension) must ship. The directory check is belt-and-braces
    # — ``zip_module``'s walk already prunes excluded dirs in place — so it
    # fires only if this helper is ever called outside that walk.
    rel_parts = filepath.relative_to(module_dir).parts
    if any(p in EXCLUDED_DIR_NAMES for p in rel_parts[:-1]):
        return True
    return filepath.suffix in EXCLUDED_SUFFIXES


class Deploy(Command):
    """Deploy a module on an Odoo instance"""

    def __init__(self) -> None:
        super().__init__()
        self.session = requests.Session()

    def deploy_module(
        self,
        module_path: str,
        url: str,
        login: str,
        password: str,
        db: str = "",
        force: bool = False,
    ) -> str:
        url = url.rstrip("/")
        module_file = self.zip_module(module_path)
        try:
            return self.login_upload_module(
                module_file, url, login, password, db, force=force
            )
        finally:
            Path(module_file).unlink()

    def login_upload_module(
        self,
        module_file: str,
        url: str,
        login: str,
        password: str,
        db: str,
        force: bool = False,
    ) -> str:
        print("Uploading module file...")
        # urlencode the db name: a db containing '&' or '#' would otherwise
        # inject extra query parameters into the login request. ``db`` may be
        # "" when the server uses a db-filter and --db is omitted; quote(None)
        # would raise TypeError, so coerce to "".
        encoded_db = urllib.parse.quote(db or "", safe="")
        self.session.get(
            f"{url}/web/login?db={encoded_db}",
            allow_redirects=False,
            timeout=_LOGIN_TIMEOUT,
        )  # this sets the db in the session
        endpoint = url + "/base_import_module/login_upload"
        post_data = {
            "login": login,
            "password": password,
            "db": db,
            "force": "1" if force else "",
        }
        with Path(module_file).open("rb") as f:
            res = self.session.post(
                endpoint,
                files={"mod_file": f},
                data=post_data,
                timeout=_UPLOAD_TIMEOUT,
            )

        if res.status_code == 404:
            raise requests.exceptions.HTTPError(
                f"The server {url!r} does not have the 'base_import_module' installed or is not up-to-date.",
                response=res,
            )
        res.raise_for_status()
        return res.text

    def zip_module(self, path: str | Path) -> str:
        """Create a zip archive of the module at ``path``.

        Returns the path to the temporary zip file.
        """
        module_dir = Path(path).resolve()
        if not module_dir.is_dir():
            raise FileNotFoundError(f"Could not find module directory {module_dir!r}")
        fd, temp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            print("Zipping module directory...")
            # ZIP_DEFLATED: the default (ZIP_STORED) uploads source files
            # uncompressed — several-fold larger for no benefit.
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zfile:
                # walk() so excluded trees (node_modules, .git, …) are pruned
                # in place and never traversed — rglob would enumerate every
                # file inside them only to discard each one.
                for dirpath, dirnames, filenames in module_dir.walk():
                    kept_dirs = []
                    for dirname in dirnames:
                        if dirname in EXCLUDED_DIR_NAMES:
                            continue
                        if (dirpath / dirname).is_symlink():
                            # walk(follow_symlinks=False) would not descend
                            # anyway; prune loudly instead of silently.
                            print(
                                f"WARNING: skipping symlink {dirpath / dirname}",
                                file=sys.stderr,
                            )
                            continue
                        kept_dirs.append(dirname)
                    dirnames[:] = kept_dirs
                    for filename in filenames:
                        filepath = dirpath / filename
                        if filepath.is_symlink():
                            # zfile.write would embed the *target's content* —
                            # a link pointing outside the module (secrets,
                            # build artifacts) must not leak into the upload.
                            print(
                                f"WARNING: skipping symlink {filepath}",
                                file=sys.stderr,
                            )
                            continue
                        if not filepath.is_file():
                            continue
                        if _should_skip(filepath, module_dir):
                            continue
                        zfile.write(filepath, filepath.relative_to(module_dir.parent))
        except Exception:
            Path(temp).unlink()
            raise
        return temp

    def run(self, cmdargs: list[str]) -> None:
        parser = self.parser
        parser.add_argument("path", help="Path of the module to deploy")
        parser.add_argument(
            "url",
            nargs="?",
            help="Url of the server (default=http://localhost:8069)",
            default="http://localhost:8069",
        )
        parser.add_argument(
            "--db",
            dest="db",
            default="",
            help="Database to use if server does not use db-filter.",
        )
        parser.add_argument(
            "--login",
            dest="login",
            default="admin",
            help="Login (default=admin)",
        )
        parser.add_argument(
            "--password",
            dest="password",
            default="admin",
            help="Password (default=admin)",
        )
        # NOTE: SSL verification is disabled by default — intentional for dev deployment
        # tooling (default URL is http://localhost:8069). Use --verify-ssl for HTTPS targets.
        parser.add_argument(
            "--verify-ssl", action="store_true", help="Verify SSL certificate"
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help='Force init even if module is already installed. (will update `noupdate="1"` records)',
        )

        # No explicit empty-args guard: argparse will fail with a clear
        # "the following arguments are required: path" message, matching
        # the convention used across the rest of the cli package.
        args = parser.parse_args(args=cmdargs)

        try:
            if not args.url.lower().startswith(("http://", "https://")):
                # Localhost defaults match the argparse default (http); remote
                # targets default to https. Resolve the host via urlsplit
                # against a synthesised authority so we match on the host
                # exactly — not on substring ('localhost.evil.com' must not
                # resolve to http), and so IPv6 loopback '[::1]' is covered.
                parsed = urllib.parse.urlsplit(f"//{args.url}", scheme="")
                hostname = (parsed.hostname or "").lower()
                scheme = "http" if hostname in _LOCAL_HOSTS else "https"
                args.url = f"{scheme}://{args.url}"

            # Warn/disable AFTER URL resolution so the decision reflects the
            # actual scheme. An earlier version warned only in the scheme-
            # inference branch, which meant a user passing 'https://host'
            # directly silently got SSL verification turned off with no
            # warning at all.
            if not args.verify_ssl:
                self.session.verify = False
                if args.url.lower().startswith("https://"):
                    print(
                        f"WARNING: SSL verification is OFF for {args.url}. "
                        "Pass --verify-ssl to verify the server certificate.",
                        file=sys.stderr,
                    )

            result = self.deploy_module(
                args.path,
                args.url,
                args.login,
                args.password,
                args.db,
                force=args.force,
            )
            print(result)
        except Exception as e:
            # Keep the full traceback recoverable at DEBUG: a programming error
            # (KeyError, AttributeError) would otherwise surface only as a bare
            # "ERROR: <msg>" with no stack — matching obfuscate.py's pattern.
            _logger.debug("deploy failed", exc_info=True)
            sys.exit(f"ERROR: {e}")
