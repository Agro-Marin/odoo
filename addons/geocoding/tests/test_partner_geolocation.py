from odoo.tests import TransactionCase


class TestPartnerGeolocationInvalidation(TransactionCase):
    """Cover when a partner's stored coordinates survive a write, and when not."""

    def test_moving_the_address_clears_the_coordinates(self):
        """Check that a write that changes the address drops the position."""
        partner = self.env["res.partner"].create(
            {
                "name": "Moving",
                "street": "Old street",
                "partner_latitude": 5.0,
                "partner_longitude": 6.0,
            }
        )

        partner.write({"street": "New street"})

        self.assertEqual(partner.partner_latitude, 0.0)
        self.assertEqual(partner.partner_longitude, 0.0)

    def test_moving_street2_clears_the_coordinates(self):
        """Check that street2 counts as part of the address.

        It was missing from the list this override checks, so editing the
        second address line moved the partner while leaving its old pin.
        """
        partner = self.env["res.partner"].create(
            {
                "name": "Second Line",
                "street": "Same street",
                "street2": "Old block",
                "partner_latitude": 5.0,
                "partner_longitude": 6.0,
            }
        )

        partner.write({"street2": "New block"})

        self.assertEqual(partner.partner_latitude, 0.0)

    def test_restating_the_same_address_keeps_the_coordinates(self):
        """Check that a write that moves no address part keeps the position.

        A caller replaying a full payload — an import, or an unchanged dict —
        used to discard a geocoding result that was still correct.
        """
        partner = self.env["res.partner"].create(
            {
                "name": "Stationary",
                "street": "Same street",
                "city": "Same city",
                "partner_latitude": 5.0,
                "partner_longitude": 6.0,
            }
        )

        partner.write({"street": "Same street", "city": "Same city"})

        self.assertEqual(partner.partner_latitude, 5.0)
        self.assertEqual(partner.partner_longitude, 6.0)

    def test_a_write_supplying_both_coordinates_keeps_them(self):
        """Check that an address write carrying a new position keeps it."""
        partner = self.env["res.partner"].create(
            {"name": "Relocated", "street": "Old street"}
        )

        partner.write(
            {
                "street": "New street",
                "partner_latitude": 7.0,
                "partner_longitude": 8.0,
            }
        )

        self.assertEqual(partner.partner_latitude, 7.0)
        self.assertEqual(partner.partner_longitude, 8.0)

    def test_a_write_supplying_one_coordinate_clears_both(self):
        """Check that half a position is refused rather than half-applied."""
        partner = self.env["res.partner"].create(
            {
                "name": "Half Located",
                "street": "Old street",
                "partner_latitude": 5.0,
                "partner_longitude": 6.0,
            }
        )

        partner.write({"street": "New street", "partner_latitude": 7.0})

        self.assertEqual(partner.partner_latitude, 0.0)
        self.assertEqual(partner.partner_longitude, 0.0)

    def test_a_write_outside_the_address_keeps_the_coordinates(self):
        """Check that a write touching no address field keeps the position."""
        partner = self.env["res.partner"].create(
            {
                "name": "Renamed",
                "street": "Same street",
                "partner_latitude": 5.0,
                "partner_longitude": 6.0,
            }
        )

        partner.write({"name": "Renamed Again"})

        self.assertEqual(partner.partner_latitude, 5.0)
        self.assertEqual(partner.partner_longitude, 6.0)

    def test_the_reset_does_not_mutate_the_caller_s_values(self):
        """Check that the coordinate reset does not leak into the caller's dict."""
        partner = self.env["res.partner"].create(
            {"name": "Shared vals", "street": "Old street"}
        )
        vals = {"street": "New street"}

        partner.write(vals)

        self.assertEqual(vals, {"street": "New street"})
