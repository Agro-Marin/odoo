import json
from unittest.mock import MagicMock, patch

import pytest

from odoo.modules import loading


class TestScanDataFile:
    def test_a_plain_xml_file_is_static(self):
        digest, dynamic = loading._scan_data_file("data/x.xml", b"<odoo></odoo>")
        assert digest
        assert dynamic is False

    def test_the_digest_follows_the_content(self):
        first, _ = loading._scan_data_file("data/x.xml", b"<odoo/>")
        same, _ = loading._scan_data_file("data/other.xml", b"<odoo/>")
        changed, _ = loading._scan_data_file("data/x.xml", b"<odoo> </odoo>")
        assert first == same, "the digest is of the content, not the name"
        assert first != changed

    @pytest.mark.parametrize("name", ["migrate.sql", "data/x.SQL", "a/b/c.sql"])
    def test_any_sql_file_is_dynamic(self, name):
        _, dynamic = loading._scan_data_file(name, b"SELECT 1;")
        assert dynamic is True, (
            "a SQL file's effect is whatever the statement does; two runs of "
            "identical bytes are not the same operation"
        )

    @pytest.mark.parametrize("marker", [b"<function", b"<delete"])
    def test_xml_carrying_a_marker_is_dynamic(self, marker):
        _, dynamic = loading._scan_data_file(
            "data/x.xml", b"<odoo>" + marker + b' model="x"/></odoo>'
        )
        assert dynamic is True, (
            "<function> runs code and <delete> removes records; neither leaves "
            "a result the file's own checksum describes"
        )

    def test_the_markers_are_matched_case_sensitively_as_xml_requires(self):
        _, dynamic = loading._scan_data_file("d.xml", b"<odoo><FUNCTION/></odoo>")
        assert dynamic is False, "XML element names are case sensitive"

    def test_a_marker_in_a_non_xml_file_does_not_make_it_dynamic(self):
        _, dynamic = loading._scan_data_file("data/x.csv", b"id,name\n<function,x\n")
        assert dynamic is False

    def test_a_file_with_no_extension_is_static(self):
        _, dynamic = loading._scan_data_file("LICENSE", b"<function/>")
        assert dynamic is False


@pytest.fixture
def loader(tmp_path):
    def _run(
        *,
        content=b"<odoo/>",
        stored=None,
        filename="data/x.xml",
        track=True,
        mode="update",
        kind="data",
    ):
        converted, recorded_xmlids = [], {"base.a", "base.b"}

        def fake_convert(env, name, fname, idref, cmode, noupdate=False):
            converted.append(fname)
            if getattr(env.registry, "_xmlid_recorder", None) is not None:
                env.registry._xmlid_recorder.update(recorded_xmlids)

        env = MagicMock()
        env.cr.fetchone.return_value = (stored,)
        registry = env.registry
        registry.loaded_xmlids = set()
        registry._xmlid_recorder = None

        package = MagicMock()
        package.name, package.id = "mymod", 42
        package.manifest = {
            "init_xml": [],
            "data": [filename] if kind == "data" else [],
            "demo": [filename] if kind == "demo" else [],
            "demo_xml": [],
        }

        handle = MagicMock()
        handle.__enter__ = MagicMock(return_value=MagicMock(read=lambda: content))
        handle.__exit__ = MagicMock(return_value=False)
        tools_mod = MagicMock(
            config={"skip_unchanged_data_files": track},
            file_open=MagicMock(return_value=handle),
        )
        with (
            patch.object(loading, "tools", tools_mod),
            patch.object(loading, "convert_file", side_effect=fake_convert),
            patch.object(loading, "schema", MagicMock(column_exists=lambda *a: track)),
        ):
            loading.load_data(env, {}, mode, kind, package)

        written = None
        for call in env.cr.execute.call_args_list:
            if "UPDATE ir_module_module" in call.args[0]:
                written = json.loads(call.args[1][0])
        return converted, registry.loaded_xmlids, written

    return _run


UNCHANGED = {"sha": None, "xmlids": ["base.a"], "dyn": False}


def _entry(digest, **over):
    return {"sha": digest, "xmlids": ["base.a"], "dyn": False, **over}


def _digest(content=b"<odoo/>", name="data/x.xml"):
    return loading._scan_data_file(name, content)[0]


class TestSkipDecision:
    def _stored(self, files):
        return {"v": loading._DATA_FILE_CHECKSUM_VERSION, "files": files}

    def test_an_unchanged_static_file_is_skipped(self, loader):
        converted, xmlids, _ = loader(
            stored=self._stored({"data/x.xml": _entry(_digest())})
        )
        assert converted == [], "the file did not change; re-applying it is waste"
        assert xmlids == {"base.a"}, (
            "the recorded xmlids must be replayed into loaded_xmlids — without "
            "them the ORM sees records nothing claims and deletes them as "
            "orphans on the next update"
        )

    def test_a_changed_file_is_re_applied(self, loader):
        converted, _, _ = loader(
            content=b"<odoo> changed </odoo>",
            stored=self._stored({"data/x.xml": _entry(_digest())}),
        )
        assert converted == ["data/x.xml"]

    def test_a_file_that_is_now_dynamic_is_never_skipped(self, loader):
        content = b'<odoo><function model="x"/></odoo>'
        converted, _, _ = loader(
            content=content,
            stored=self._stored({"data/x.xml": _entry(_digest(content), dyn=False)}),
        )
        assert converted == ["data/x.xml"], (
            "the checksum matches, but <function> runs code — the previous "
            "run's effect is not reproduced by the file being identical"
        )

    def test_a_file_that_WAS_dynamic_is_never_skipped(self, loader):
        converted, _, _ = loader(
            stored=self._stored({"data/x.xml": _entry(_digest(), dyn=True)})
        )
        assert converted == ["data/x.xml"], (
            "it was dynamic when last applied, so what it did then is unknown; "
            "the `dyn` flag has to be checked on the STORED entry too"
        )

    def test_an_entry_with_no_recorded_xmlids_is_never_skipped(self, loader):
        entry = _entry(_digest())
        del entry["xmlids"]
        converted, _, _ = loader(stored=self._stored({"data/x.xml": entry}))
        assert converted == ["data/x.xml"], (
            "skipping without the xmlids to replay leaves loaded_xmlids short, "
            "and the records it should have named get deleted as orphans"
        )

    def test_a_malformed_entry_is_never_skipped(self, loader):
        converted, _, _ = loader(stored=self._stored({"data/x.xml": "not-a-dict"}))
        assert converted == ["data/x.xml"]

    def test_a_store_from_an_older_format_version_is_ignored(self, loader):
        converted, _, _ = loader(
            stored={
                "v": loading._DATA_FILE_CHECKSUM_VERSION - 1,
                "files": {"data/x.xml": _entry(_digest())},
            }
        )
        assert converted == ["data/x.xml"], (
            "an entry written by an older scanner may mean something else; "
            "reading it as current is how a format change becomes data loss"
        )

    def test_a_file_never_seen_before_is_applied(self, loader):
        converted, _, _ = loader(stored=self._stored({}))
        assert converted == ["data/x.xml"]

    def test_with_tracking_off_nothing_is_skipped_and_nothing_is_written(self, loader):
        converted, _, written = loader(
            track=False, stored=self._stored({"data/x.xml": _entry(_digest())})
        )
        assert converted == ["data/x.xml"]
        assert written is None


class TestWhatGetsRecorded:
    def _stored(self, files):
        return {"v": loading._DATA_FILE_CHECKSUM_VERSION, "files": files}

    def test_a_freshly_applied_file_records_its_digest_and_xmlids(self, loader):
        _, _, written = loader(stored=self._stored({}))
        entry = written["files"]["data/x.xml"]
        assert entry["sha"] == _digest()
        assert entry["xmlids"] == ["base.a", "base.b"], "sorted, so it is stable"
        assert entry["dyn"] is False

    def test_a_dynamic_file_records_that_it_was_dynamic(self, loader):
        content = b'<odoo><delete model="x"/></odoo>'
        _, _, written = loader(content=content, stored=self._stored({}))
        assert written["files"]["data/x.xml"]["dyn"] is True, (
            "recording it as static would let the NEXT run skip it"
        )

    def test_the_store_carries_its_format_version(self, loader):
        _, _, written = loader(stored=self._stored({}))
        assert written["v"] == loading._DATA_FILE_CHECKSUM_VERSION

    def test_a_skipped_file_stays_in_the_store(self, loader):
        entry = _entry(_digest())
        _, _, written = loader(stored=self._stored({"data/x.xml": entry}))
        assert written["files"]["data/x.xml"] == entry, (
            "dropping a skipped file's entry means the next run cannot skip it "
            "either, and the optimisation decays to nothing over time"
        )
