import argparse
import logging
import os
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

import requests

from odoo.libs.debug_log import DebugLog

from . import Command

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)

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
        ".vscode",
        "dist",
        "build",
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
EXCLUDED_FILE_NAMES = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
    }
)

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

_LOGIN_TIMEOUT = (10, 30)
_UPLOAD_TIMEOUT = (10, None)


def _is_file_excluded(filepath: Path) -> bool:
    return filepath.suffix in EXCLUDED_SUFFIXES or filepath.name in EXCLUDED_FILE_NAMES


class Deploy(Command):
    description = "Deploy a module on an Odoo instance"

    def __init__(self) -> None:
        super().__init__()
        self.session = requests.Session()
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
        parser.add_argument(
            "--no-verify-ssl",
            dest="verify_ssl",
            action="store_false",
            default=True,
            help="Do NOT verify the server's SSL certificate (insecure: "
            "credentials are sent in the request body)",
        )
        parser.add_argument(
            "--verify-ssl",
            dest="verify_ssl",
            action="store_true",
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help='Force init even if module is already installed. (will update `noupdate="1"` records)',
        )

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
            _debug.lifecycle("cli.deploy.zip_removed", path=module_file)

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
        encoded_db = urllib.parse.quote(db or "", safe="")
        with _debug.perf("cli.deploy.login_page", url=url, db=db or None):
            self.session.get(
                f"{url}/web/login?db={encoded_db}",
                allow_redirects=False,
                timeout=_LOGIN_TIMEOUT,
            )
        endpoint = url + "/base_import_module/login_upload"
        post_data = {
            "login": login,
            "password": password,
            "db": db,
            "force": "1" if force else "",
        }
        with Path(module_file).open("rb") as f:
            with _debug.perf(
                "cli.deploy.upload",
                url=url,
                db=db or None,
                force=force,
                bytes=Path(module_file).stat().st_size,
            ) as span:
                res = self.session.post(
                    endpoint,
                    files={"mod_file": f},
                    data=post_data,
                    timeout=_UPLOAD_TIMEOUT,
                )
                span.set(status=res.status_code)

        if res.status_code == 404:
            _debug.logic("cli.deploy.upload_rejected", status=404, url=url)
            raise requests.exceptions.HTTPError(
                f"The server {url!r} does not have the 'base_import_module' installed or is not up-to-date.",
                response=res,
            )
        if _debug.logic.enabled and not res.ok:
            _debug.logic("cli.deploy.upload_rejected", status=res.status_code, url=url)
        res.raise_for_status()
        return res.text

    def zip_module(self, path: str | Path) -> str:
        module_dir = Path(path).resolve()
        if not module_dir.is_dir():
            raise FileNotFoundError(f"Could not find module directory {module_dir!r}")
        fd, temp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            print("Zipping module directory...")
            with _debug.perf("cli.deploy.zip", module=module_dir.name) as span:
                files = 0  # debuglog
                symlinks = 0  # debuglog
                with zipfile.ZipFile(
                    temp, "w", compression=zipfile.ZIP_DEFLATED
                ) as zfile:
                    for dirpath, dirnames, filenames in module_dir.walk():
                        kept_dirs = []
                        for dirname in dirnames:
                            if dirname in EXCLUDED_DIR_NAMES:
                                continue
                            if (dirpath / dirname).is_symlink():
                                symlinks += 1  # debuglog
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
                                symlinks += 1  # debuglog
                                print(
                                    f"WARNING: skipping symlink {filepath}",
                                    file=sys.stderr,
                                )
                                continue
                            if not filepath.is_file():
                                continue
                            if _is_file_excluded(filepath):
                                continue
                            zfile.write(
                                filepath, filepath.relative_to(module_dir.parent)
                            )
                            files += 1  # debuglog
                span.set(
                    files=files, symlinks=symlinks, bytes=Path(temp).stat().st_size
                )
        except Exception as e:
            _debug.logic("cli.deploy.zip_failed", error=type(e).__name__)
            Path(temp).unlink()
            raise
        return temp

    def run(self, cmdargs: list[str]) -> None:
        args = self.parser.parse_args(args=cmdargs)

        try:
            if not args.url.lower().startswith(("http://", "https://")):
                parsed = urllib.parse.urlsplit(f"//{args.url}", scheme="")
                hostname = (parsed.hostname or "").lower()
                scheme = "http" if hostname in _LOCAL_HOSTS else "https"
                args.url = f"{scheme}://{args.url}"
                _debug.logic("cli.deploy.scheme_inferred", scheme=scheme, host=hostname)

            if not args.verify_ssl:
                self.session.verify = False
                _debug.logic(
                    "cli.deploy.ssl_verification",
                    verify=False,
                    https=args.url.lower().startswith("https://"),
                )
                if args.url.lower().startswith("https://"):
                    print(
                        f"WARNING: SSL verification is OFF for {args.url}; "
                        "the login and password below are sent to an "
                        "unauthenticated server. Drop --no-verify-ssl to "
                        "verify the certificate.",
                        file=sys.stderr,
                    )
                    import urllib3

                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            with self.session:
                with _debug.perf(
                    "cli.deploy.run", path=args.path, url=args.url, force=args.force
                ):
                    result = self.deploy_module(
                        args.path,
                        args.url,
                        args.login,
                        args.password,
                        args.db,
                        force=args.force,
                    )
            print(result or "Module deployed successfully.")
        except Exception as e:
            _debug.logic("cli.deploy.failed", error=type(e).__name__)
            _logger.debug("deploy failed", exc_info=True)
            sys.exit(f"ERROR: {e}")
