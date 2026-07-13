"""Regression tests for the embedded-Sass binary discovery probe.

Focus: commit 7b338eee7f92 fixed ``find_sass``/``_supports_embedded`` to
verify a candidate actually speaks the Embedded Sass Protocol (not just that
some binary named ``sass`` exists on PATH) — a pure-JS ``sass`` or a
wrong-platform bundled binary both accept ``--embedded`` but silently degrade
every SCSS compile to the slow per-bundle CLI. This locks that behaviour so a
future packaging change can't regress it silently again.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from odoo.tools.sass_embedded import _supports_embedded, find_sass


class TestSupportsEmbedded(unittest.TestCase):
    """_supports_embedded() probes the binary by actually launching it."""

    def _run(self, returncode: int = 0, stdout: bytes = b"") -> MagicMock:
        """Build a fake completed-process object for a mocked subprocess.run."""
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        return proc

    def test_native_dart_sass_returns_true(self) -> None:
        """Exit 0, no diagnostic marker: a real embedded-capable binary."""
        with patch("subprocess.run", return_value=self._run(0, b"")):
            self.assertTrue(_supports_embedded("/usr/bin/sass"))

    def test_pure_js_sass_returns_false(self) -> None:
        """The npm pure-JS package prints its own unavailability marker."""
        with patch(
            "subprocess.run",
            return_value=self._run(
                1, b"sass --embedded is unavailable in pure JS mode"
            ),
        ):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))

    def test_wrong_platform_binary_returns_false(self) -> None:
        """A wrong-platform bundled binary fails to exec its inner dart binary."""
        with patch("subprocess.run", return_value=self._run(127, b"")):
            self.assertFalse(
                _supports_embedded("/opt/sass-embedded-linux-musl/dart-sass/sass")
            )

    def test_zero_exit_with_marker_returns_false(self) -> None:
        """Exit 0 does not override a marker present in stdout.

        Guards against a hypothetical build that prints the diagnostic but
        (for whatever reason) still exits cleanly.
        """
        with patch(
            "subprocess.run",
            return_value=self._run(0, b"sass --embedded is unavailable in pure JS mode"),
        ):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))

    def test_nonzero_exit_without_marker_returns_false(self) -> None:
        """Any non-zero exit is untrusted, marker or not."""
        with patch("subprocess.run", return_value=self._run(1, b"some other failure")):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))

    def test_oserror_returns_false(self) -> None:
        """A binary that isn't even executable must not raise — just fail."""
        with patch("subprocess.run", side_effect=OSError("not executable")):
            self.assertFalse(_supports_embedded("/nonexistent/sass"))

    def test_subprocess_error_returns_false(self) -> None:
        """A timeout or other SubprocessError also degrades to False."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sass", timeout=10),
        ):
            self.assertFalse(_supports_embedded("/usr/bin/sass"))


class TestFindSass(unittest.TestCase):
    """find_sass() only returns a candidate VERIFIED by _supports_embedded."""

    def test_skips_unverified_system_sass_falls_back_to_node_modules_cli(
        self,
    ) -> None:
        """A system sass failing the probe falls back to the CLI, not itself.

        It's still used as the final CLI fallback if nothing else matches.
        """
        with (
            patch("shutil.which") as which_mock,
            patch("pathlib.Path.glob", return_value=iter([])),
            patch(
                "odoo.tools.sass_embedded._supports_embedded", return_value=False
            ),
        ):
            # First call: system `sass` lookup. Second call: node_modules/.bin
            # CLI fallback lookup (scoped by the `path=` kwarg in find_sass).
            which_mock.side_effect = [
                "/usr/bin/sass",
                "/app/node_modules/.bin/sass",
            ]
            result = find_sass()
        self.assertEqual(result, "/app/node_modules/.bin/sass")

    def test_returns_first_verified_embedded_candidate(self) -> None:
        """The first candidate that passes the probe wins, system PATH first."""
        with (
            patch("shutil.which", return_value="/usr/bin/sass"),
            patch("pathlib.Path.glob", return_value=iter([])),
            patch(
                "odoo.tools.sass_embedded._supports_embedded", return_value=True
            ),
        ):
            result = find_sass()
        self.assertEqual(result, "/usr/bin/sass")

    def test_no_system_sass_and_no_bundled_binary_returns_none(self) -> None:
        """Nothing on PATH, nothing bundled, no CLI fallback: None."""
        with (
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.glob", return_value=iter([])),
        ):
            result = find_sass()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
