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
    }
)
# Matched against the file NAME, not the suffix: for a dotfile like
# `.DS_Store`, Path.suffix is '' (the leading dot marks a hidden file, not an
# extension), so a suffix check never fires.
EXCLUDED_FILE_NAMES = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
    }
)

# Hosts that deploy treats as local and therefore defaults to http://.
# Exact host match only (substring matches would let 'localhost.evil.com'
# bypass TLS).
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

# (connect, read) timeouts. requests has no default, so a stuck server would
# hang forever. Connect fails fast; the upload read is unbounded because the
# server installs synchronously and large modules take minutes.
_LOGIN_TIMEOUT = (10, 30)
_UPLOAD_TIMEOUT = (10, None)


def _should_skip(filepath: Path, module_dir: Path) -> bool:
    """Return True if ``filepath`` should be excluded from the deploy zip."""
    # Match parent components against EXCLUDED_DIR_NAMES, never the basename: a
    # module file named `build`/`dist` must still ship. Redundant with
    # zip_module's walk, which already prunes excluded dirs in place.
    rel_parts = filepath.relative_to(module_dir).parts
    if any(p in EXCLUDED_DIR_NAMES for p in rel_parts[:-1]):
        return True
    return filepath.suffix in EXCLUDED_SUFFIXES or filepath.name in EXCLUDED_FILE_NAMES


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
        # urlencode the db name: '&'/'#' would inject extra query params. db may
        # be "" (server uses a db-filter, --db omitted); quote(None) would raise.
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
            # ZIP_DEFLATED: the default ZIP_STORED uploads uncompressed, much larger.
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zfile:
                # walk() so excluded trees are pruned in place and never
                # traversed; rglob would enumerate every file only to discard it.
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
                            # zfile.write embeds the target's content; a link
                            # outside the module must not leak into the upload.
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
        # SSL verification is off by default — this is dev tooling (default URL
        # is http://localhost:8069). Use --verify-ssl for HTTPS targets.
        parser.add_argument(
            "--verify-ssl", action="store_true", help="Verify SSL certificate"
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help='Force init even if module is already installed. (will update `noupdate="1"` records)',
        )

        # No empty-args guard: argparse already errors with "the following
        # arguments are required: path".
        args = parser.parse_args(args=cmdargs)

        try:
            if not args.url.lower().startswith(("http://", "https://")):
                # Local hosts default to http, remote to https. Parse via a
                # synthesised authority to match the host exactly (not by
                # substring) and to cover IPv6 loopback '[::1]'.
                parsed = urllib.parse.urlsplit(f"//{args.url}", scheme="")
                hostname = (parsed.hostname or "").lower()
                scheme = "http" if hostname in _LOCAL_HOSTS else "https"
                args.url = f"{scheme}://{args.url}"

            # Decide AFTER URL resolution so it reflects the actual scheme:
            # a user passing 'https://host' directly must still get the warning.
            if not args.verify_ssl:
                self.session.verify = False
                if args.url.lower().startswith("https://"):
                    print(
                        f"WARNING: SSL verification is OFF for {args.url}. "
                        "Pass --verify-ssl to verify the server certificate.",
                        file=sys.stderr,
                    )
                    # One clear warning is enough; without this, urllib3
                    # repeats an InsecureRequestWarning for every request.
                    import urllib3

                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            result = self.deploy_module(
                args.path,
                args.url,
                args.login,
                args.password,
                args.db,
                force=args.force,
            )
            # The upload endpoint may return an empty body on success; a blank
            # line reads as "something went wrong", so say it plainly.
            print(result or "Module deployed successfully.")
        except Exception as e:
            # Keep the full traceback at DEBUG: a programming error would
            # otherwise surface only as a bare "ERROR: <msg>" with no stack.
            _logger.debug("deploy failed", exc_info=True)
            sys.exit(f"ERROR: {e}")
