import unittest

from addons.account.tools.structured_reference import (
    is_valid_structured_reference,
    is_valid_structured_reference_be,
    is_valid_structured_reference_dk,
    is_valid_structured_reference_fi,
    is_valid_structured_reference_iso,
    is_valid_structured_reference_nl,
    is_valid_structured_reference_no_se,
    is_valid_structured_reference_si,
)


class StructuredReferenceTest(unittest.TestCase):
    def test_structured_reference_iso(self):
        self.assertTrue(is_valid_structured_reference_iso(" RF18 5390 0754 7034 "))
        self.assertTrue(is_valid_structured_reference_iso(" RF18539007547034"))
        self.assertTrue(is_valid_structured_reference_iso("RF18000000000539007547034"))

        self.assertFalse(is_valid_structured_reference_iso("18539007547034RF"))
        self.assertFalse(is_valid_structured_reference_iso("RF17539007547034"))
        self.assertFalse(
            is_valid_structured_reference_be("RF18539007547034-OTHER-RANDOM-STUFF")
        )

    def test_structured_reference_be(self):
        self.assertTrue(is_valid_structured_reference_be(" +++020/3430/57642+++"))
        self.assertTrue(is_valid_structured_reference_be("***020/3430/57642*** "))
        self.assertTrue(is_valid_structured_reference_be(" 020343057642"))
        self.assertTrue(is_valid_structured_reference_be("020343053497"))
        self.assertFalse(is_valid_structured_reference_be("020343053400"))
        self.assertTrue(is_valid_structured_reference_be("020343053501"))
        self.assertFalse(is_valid_structured_reference_be("020343053598"))

        self.assertFalse(is_valid_structured_reference_be("***02/03430/57642***"))
        self.assertFalse(is_valid_structured_reference_be("020343057641"))
        self.assertFalse(
            is_valid_structured_reference_be("020343053497-OTHER-RANDOM-STUFF")
        )

    def test_structured_reference_dk(self):
        self.assertTrue(
            is_valid_structured_reference_dk("+71<022646321691226+12345678<")
        )
        self.assertTrue(
            is_valid_structured_reference_dk("71<022646321691226+12345678<")
        )
        self.assertTrue(
            is_valid_structured_reference_dk(" +71<022646321691226+12345678< ")
        )
        self.assertTrue(
            is_valid_structured_reference_dk("+75<0226463216912202+12345678<")
        )

        self.assertFalse(
            is_valid_structured_reference_dk("+71<022646321691227+12345678<")
        )
        self.assertFalse(is_valid_structured_reference_dk("random"))
        self.assertFalse(is_valid_structured_reference_dk("+71<12345+12345678<"))
        self.assertFalse(
            is_valid_structured_reference_dk("+71<022646321691226+12345678<XXX")
        )

    def test_structured_reference_fi(self):
        self.assertTrue(is_valid_structured_reference_fi("2023 0000 98"))
        self.assertTrue(is_valid_structured_reference_fi("2023000098"))
        self.assertTrue(is_valid_structured_reference_fi("00000000002023000098"))

        self.assertFalse(is_valid_structured_reference_fi("2023/0000/98"))
        self.assertFalse(is_valid_structured_reference_fi("000000000002023000098"))
        self.assertFalse(is_valid_structured_reference_fi("2023000095"))
        self.assertFalse(
            is_valid_structured_reference_fi("2023000098-OTHER-RANDOM-STUFF")
        )

    def test_structured_reference_no_se(self):
        self.assertTrue(is_valid_structured_reference_no_se("1234 5678 97"))
        self.assertTrue(is_valid_structured_reference_no_se("1234567897"))
        self.assertTrue(is_valid_structured_reference_no_se("000001234567897"))

        self.assertFalse(is_valid_structured_reference_no_se("1234/5678/97"))
        self.assertFalse(is_valid_structured_reference_no_se("1234567898"))
        self.assertFalse(
            is_valid_structured_reference_no_se("1234567897-OTHER-RANDOM-STUFF")
        )

    def test_structured_reference_si(self):
        self.assertTrue(is_valid_structured_reference_si("SI01 25-20-85"))
        self.assertTrue(is_valid_structured_reference_si("  SI01 25  - 2 0-85  "))
        self.assertTrue(is_valid_structured_reference_si("SI01 19-1235-84505"))

        self.assertFalse(is_valid_structured_reference_si("SI01 25-20-84"))
        self.assertFalse(is_valid_structured_reference_si("SI01 19-1235-84504"))

        self.assertFalse(is_valid_structured_reference_si("SI02 25-20-85"))
        self.assertFalse(is_valid_structured_reference_si("0519123584503"))

        self.assertFalse(is_valid_structured_reference_si("SI01 252085"))
        self.assertFalse(is_valid_structured_reference_si("SI01 25-2085"))
        self.assertFalse(is_valid_structured_reference_si("SI01 25--20-85"))

        self.assertFalse(is_valid_structured_reference_si("SI01 ab-cd-ef"))
        self.assertFalse(is_valid_structured_reference_si("SI01 25-20-"))
        self.assertFalse(is_valid_structured_reference_si("SI01"))

    def test_structured_reference_nl(self):
        self.assertTrue(is_valid_structured_reference_nl("1234567"))

        self.assertTrue(is_valid_structured_reference_nl("271234567"))

        self.assertTrue(is_valid_structured_reference_nl("42234567890123"))

        self.assertTrue(is_valid_structured_reference_nl("5000056789012345"))

        self.assertTrue(
            is_valid_structured_reference_nl("0123456788")
        )
        self.assertTrue(
            is_valid_structured_reference_nl("123456789107")
        )

        self.assertTrue(is_valid_structured_reference_nl("5 000 0567 8901 2345"))
        self.assertTrue(is_valid_structured_reference_nl("   5000056789012345   "))

        self.assertFalse(is_valid_structured_reference_nl("123456"))
        self.assertFalse(is_valid_structured_reference_nl("12345678"))
        self.assertFalse(is_valid_structured_reference_nl("123456789012345"))
        self.assertFalse(is_valid_structured_reference_nl("12345678901234567"))
        self.assertFalse(is_valid_structured_reference_nl("4000056789012345"))
        self.assertFalse(
            is_valid_structured_reference_nl("5000056789012345-OTHER-RANDOM-STUFF")
        )

    def test_structured_reference(self):
        self.assertTrue(is_valid_structured_reference(" RF18 5390 0754 7034 "))
        self.assertTrue(is_valid_structured_reference(" +++020/3430/57642+++"))
        self.assertTrue(is_valid_structured_reference("***020/3430/57642*** "))
        self.assertTrue(is_valid_structured_reference("2023 0000 98"))
        self.assertTrue(is_valid_structured_reference("1234 5678 97"))
        self.assertTrue(is_valid_structured_reference("SI01 25-20-85"))
        self.assertTrue(is_valid_structured_reference("5000056789012345"))
        self.assertTrue(is_valid_structured_reference(" RF18539007547034"))
        self.assertTrue(is_valid_structured_reference(" 020343057642"))
        self.assertTrue(is_valid_structured_reference("2023000098"))
        self.assertTrue(is_valid_structured_reference("1234567897"))
        self.assertTrue(is_valid_structured_reference("  SI01 25  - 2 0-85  "))
        self.assertTrue(is_valid_structured_reference("5 000 0567 8901 2345"))
        self.assertTrue(
            is_valid_structured_reference("RF18000000000539007547034")
        )
        self.assertTrue(is_valid_structured_reference("00000000002023000098"))
        self.assertTrue(is_valid_structured_reference("000001234567897"))

        self.assertFalse(is_valid_structured_reference("18539007547034RF"))
        self.assertFalse(is_valid_structured_reference("***02/03430/57642***"))
        self.assertFalse(is_valid_structured_reference("2023/0000/98"))
        self.assertFalse(is_valid_structured_reference("1234/5678/97"))
        self.assertFalse(is_valid_structured_reference("0519123584503"))
        self.assertFalse(is_valid_structured_reference("(5)000 0567 8901 2345"))
        self.assertFalse(is_valid_structured_reference("RF17539007547034"))
        self.assertFalse(is_valid_structured_reference("020343057641"))
        self.assertFalse(is_valid_structured_reference("2023000095"))
        self.assertFalse(is_valid_structured_reference("1234567898"))
        self.assertFalse(is_valid_structured_reference("SI01 19-1235-84504"))
        self.assertFalse(is_valid_structured_reference("6000056789012345"))
