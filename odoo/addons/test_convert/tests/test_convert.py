import base64
from typing import NamedTuple

from lxml import etree as ET
from lxml.builder import E

from odoo.tests import common
from odoo.tools.convert import _eval_xml, convert_file, xml_import
from odoo.tools.misc import file_path


class _Obj(NamedTuple):
    module: str
    idref: object


Field = E.field
Value = E.value


class TestEvalXML(common.TransactionCase):
    def eval_xml(self, node, obj=None):
        return _eval_xml(obj, node, self.env)

    def test_char(self):
        self.assertEqual(self.eval_xml(Field("foo")), "foo")
        self.assertEqual(self.eval_xml(Field("None")), "None")

    def test_int(self):
        self.assertIsNone(
            self.eval_xml(Field("None", type="int")),
            "'None' with type=int must eval to None",
        )
        self.assertEqual(self.eval_xml(Field(" 42  ", type="int")), 42)

        with self.assertRaises(ValueError):
            self.eval_xml(Field("4.82", type="int"))

        with self.assertRaises(ValueError):
            self.eval_xml(Field("Whelp", type="int"))

    def test_float(self):
        self.assertEqual(self.eval_xml(Field("4.78", type="float")), 4.78)

        with self.assertRaises(ValueError):
            self.eval_xml(Field("None", type="float"))

        with self.assertRaises(ValueError):
            self.eval_xml(Field("Foo", type="float"))

    def test_list(self):
        self.assertEqual(self.eval_xml(Field(type="list")), [])

        self.assertEqual(
            self.eval_xml(
                Field(
                    Value("foo"),
                    Value("5", type="int"),
                    Value("4.76", type="float"),
                    Value("None", type="int"),
                    type="list",
                )
            ),
            ["foo", 5, 4.76, None],
        )

    def test_tuple(self):
        self.assertEqual(self.eval_xml(Field(type="tuple")), ())

        self.assertEqual(
            self.eval_xml(
                Field(
                    Value("foo"),
                    Value("5", type="int"),
                    type="tuple",
                )
            ),
            ("foo", 5),
        )

    def test_file(self):
        Obj = _Obj
        obj = Obj("test_convert", None)
        self.assertEqual(
            self.eval_xml(Field("test_file.txt", type="file"), obj),
            "test_convert,test_file.txt",
        )

        with self.assertRaises(IOError):
            self.eval_xml(Field("test_nofile.txt", type="file"), obj)

    def test_base64(self):
        result = self.eval_xml(Field(type="base64", file="test_convert/test_file.txt"))
        self.assertEqual(
            base64.b64decode(result).rstrip(b"\n"),
            b"nothing to see here, move along",
        )

        with self.assertRaises(ValueError):
            self.eval_xml(Field("anything", type="base64"))

    def test_function(self):
        obj = xml_import(self.env, "test_convert", None, "init")

        xml = E.function(
            model="test_convert.usered",
            name="model_method",
            eval="[1, 2]",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, self.env.context)
        self.assertEqual(rec.ids, [])
        self.assertEqual(args, (1, 2))
        self.assertEqual(kwargs, {})

        xml = E.function(
            model="test_convert.usered",
            name="method",
            eval="[1, 2]",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, self.env.context)
        self.assertEqual(rec.ids, [1])
        self.assertEqual(args, (2,))
        self.assertEqual(kwargs, {})

        xml = E.function(
            E.value(eval="1"),
            E.value(eval="2"),
            model="test_convert.usered",
            name="model_method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, self.env.context)
        self.assertEqual(rec.ids, [])
        self.assertEqual(args, (1, 2))
        self.assertEqual(kwargs, {})

        xml = E.function(
            E.value(eval="1"),
            E.value(eval="2"),
            model="test_convert.usered",
            name="method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, self.env.context)
        self.assertEqual(rec.ids, [1])
        self.assertEqual(args, (2,))
        self.assertEqual(kwargs, {})

    def test_function_kwargs(self):
        obj = xml_import(self.env, "test_convert", None, "init")

        xml = E.function(
            E.value(eval="1"),
            E.value(name="foo", eval="2"),
            model="test_convert.usered",
            name="model_method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, self.env.context)
        self.assertEqual(rec.ids, [])
        self.assertEqual(args, (1,))
        self.assertEqual(kwargs, {"foo": 2})

        xml = E.function(
            E.value(eval="1"),
            E.value(name="foo", eval="2"),
            model="test_convert.usered",
            name="method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, self.env.context)
        self.assertEqual(rec.ids, [1])
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {"foo": 2})

        xml = E.function(
            E.value(eval="1"),
            E.value(name="context", eval="{'foo': 2}"),
            model="test_convert.usered",
            name="model_method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, {"foo": 2})
        self.assertEqual(rec.ids, [])
        self.assertEqual(args, (1,))
        self.assertEqual(kwargs, {})

        xml = E.function(
            E.value(eval="1"),
            E.value(name="context", eval="{'foo': 2}"),
            model="test_convert.usered",
            name="method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, {"foo": 2})
        self.assertEqual(rec.ids, [1])
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {})

    def test_function_function(self):
        obj = xml_import(self.env, "test_convert", None, "init")

        xml = E.function(
            E.function(model="test_convert.usered", name="search", eval="[[]]"),
            model="test_convert.usered",
            name="method",
        )
        rec, args, kwargs = self.eval_xml(xml, obj)
        self.assertEqual(rec.env.context, {})
        self.assertEqual(rec.ids, [])
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {})

    def test_o2m_sub_records(self):
        Model = self.registry["test_convert.test_model"]
        call_args = []

        def _load_records(self, data_list, update=False):
            call_args.append(data_list)
            return super(Model, self)._load_records(data_list, update=update)

        self.patch(Model, "_load_records", _load_records)

        xml = ET.fromstring(
            """
            <record id="test_convert.test_o2m_record" model="test_convert.test_model">
                <field name="usered_ids">
                    <record id="test_convert.test_o2m_subrecord" model="test_convert.usered">
                        <field name="name">subrecord</field>
                    </record>
                </field>
            </record>
        """.strip()
        )
        obj = xml_import(self.env, "test_convert", None, "init")
        obj._tag_record(xml)

        self.assertEqual(len(call_args), 1)
        for data in call_args[0]:
            self.assertNotIn(
                "usered_ids",
                data["values"],
                "Unexpected value in O2M When loading XML with sub records",
            )

    def test_o2m_sub_records_noupdate(self):
        xml = ET.fromstring(
            """
            <data noupdate="1">
              <record id="test_convert.test_o2m_record_noup" model="test_convert.test_model">
                <field name="usered_ids">
                    <record id="test_convert.test_o2m_subrecord_noup" model="test_convert.usered">
                        <field name="name">subrecord</field>
                    </record>
                </field>
              </record>
            </data>
        """.strip()
        )

        xmlids = {
            "test_convert.test_o2m_record_noup",
            "test_convert.test_o2m_subrecord_noup",
        }

        xml_import(self.env, "test_convert", None, "init").parse(xml)

        # loaded_xmlids lives on the process-wide registry, not the test's
        # transaction -- restore it even if an assertion below raises, so a
        # failure here can't leak stale state into a sibling test.
        self.registry.loaded_xmlids.difference_update(xmlids)
        self.addCleanup(self.registry.loaded_xmlids.update, xmlids)

        idref = {}
        xml_import(self.env, "test_convert", idref, "update").parse(xml)

        self.assertEqual(set(idref.keys()), xmlids)
        self.assertTrue(self.registry.loaded_xmlids.issuperset(xmlids))

    def test_translated_field(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        env_fr = self.env(context=dict(self.env.context, lang="fr_FR"))
        record = self.env.ref("test_convert.test_translated_field")

        record.name = "bar"
        self.assertEqual(record.name, "bar")
        filepath = file_path(
            "test_convert/data/test_translated_field/test_model_data.xml"
        )
        doc = ET.parse(filepath)
        obj = xml_import(env_fr, "test_convert", {}, mode="init", xml_filename=filepath)
        obj.parse(doc.getroot())
        self.assertEqual(record.with_context(lang=None).name, "foo")

        record.name = "bar"
        self.assertEqual(record.name, "bar")
        convert_file(
            env_fr,
            "test_convert",
            "data/test_translated_field/test_model_data.xml",
            {},
        )
        self.assertEqual(record.with_context(lang=None).name, "foo")

        record.name = "bar"
        self.assertEqual(record.name, "bar")
        convert_file(
            env_fr,
            "test_convert",
            "data/test_translated_field/test_convert.test_model.csv",
            {},
        )
        self.assertEqual(record.with_context(lang=None).name, "foo")

    def test_xml(self):
        self.assertEqual(
            self.eval_xml(
                Field(
                    ET.fromstring("<parent><child/></parent>"),
                    type="xml",
                )
            ),
            '<?xml version="1.0"?>\n<parent><child/></parent>',
        )

    def test_html(self):
        self.assertEqual(
            self.eval_xml(
                Field(
                    ET.fromstring("""<parent>
                <t t-if="True">
                    <t t-out="'text'"/>
                </t>
                <t t-else="">
                    <t t-out="'text2'"></t>
                </t>
            </parent>"""),
                    type="html",
                )
            ),
            """<parent>
                <t t-if="True">
                    <t t-out="'text'"></t>
                </t>
                <t t-else="">
                    <t t-out="'text2'"></t>
                </t>
            </parent>""",
            "Evaluating an HTML field should give empty nodes instead of self-closing tags",
        )
