import subprocess
import unittest
from unittest.mock import MagicMock, patch

from odoo.tools.sass_embedded import _supports_embedded, find_sass


class TestSupportsEmbedded(unittest.TestCase):
    def _run(self, returncode: int = 0, stdout: bytes = b"") -> MagicMock:
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        return proc

    def test_native_dart_sass_returns_true(self) -> None:
        with patch("subprocess.run", return_value=self._run(0, b"")):
            self.assertTrue(_supports_embedded("/usr/bin/sass"))

    def test_pure_js_sass_returns_false(self) -> None:
        with patch(
            "subprocess.run",
            return_value=self._run(
                1, b"sass --embedded is unavailable in pure JS mode"
            ),
        ):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))

    def test_wrong_platform_binary_returns_false(self) -> None:
        with patch("subprocess.run", return_value=self._run(127, b"")):
            self.assertFalse(
                _supports_embedded("/opt/sass-embedded-linux-musl/dart-sass/sass")
            )

    def test_zero_exit_with_marker_returns_false(self) -> None:
        with patch(
            "subprocess.run",
            return_value=self._run(
                0, b"sass --embedded is unavailable in pure JS mode"
            ),
        ):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))

    def test_nonzero_exit_without_marker_returns_false(self) -> None:
        with patch("subprocess.run", return_value=self._run(1, b"some other failure")):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))

    def test_oserror_returns_false(self) -> None:
        with patch("subprocess.run", side_effect=OSError("not executable")):
            self.assertFalse(_supports_embedded("/nonexistent/sass"))

    def test_subprocess_error_returns_false(self) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sass", timeout=10),
        ):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))


class TestFindSass(unittest.TestCase):
    def test_skips_unverified_system_sass_falls_back_to_node_modules_cli(
        self,
    ) -> None:
        with (
            patch("shutil.which") as which_mock,
            patch("pathlib.Path.glob", return_value=iter([])),
            patch("odoo.tools.sass_embedded._supports_embedded", return_value=False),
        ):
            which_mock.side_effect = [
                "/usr/bin/sass",
                "/app/node_modules/.bin/sass",
            ]
            result = find_sass()
        self.assertEqual(result, "/app/node_modules/.bin/sass")

    def test_returns_first_verified_embedded_candidate(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/sass"),
            patch("pathlib.Path.glob", return_value=iter([])),
            patch("odoo.tools.sass_embedded._supports_embedded", return_value=True),
        ):
            result = find_sass()
        self.assertEqual(result, "/usr/bin/sass")

    def test_no_system_sass_and_no_bundled_binary_returns_none(self) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.glob", return_value=iter([])),
        ):
            result = find_sass()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
