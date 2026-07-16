"""Inalterability hash chain for account.move.

Split out of account_move.py: the hash/integrity cluster has no override in
any inheriting module and forms a self-contained responsibility (see
_get_integrity_hash_fields for the extension hook l10n modules use).
"""

from hashlib import sha256
from json import dumps

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import float_repr

from .account_move import MAX_HASH_VERSION
from .account_move import AccountMove as AccountMoveMain


class AccountMove(models.Model):
    _inherit = "account.move"

    def _get_integrity_hash_fields(self):
        # Use the latest hash version by default, but keep the old one for backward compatibility when generating the integrity report.
        hash_version = self.env.context.get("hash_version", MAX_HASH_VERSION)
        if hash_version == 1:
            return ["date", "journal_id", "company_id"]
        elif hash_version in (2, 3, 4):
            return ["name", "date", "journal_id", "company_id"]
        raise NotImplementedError(f"hash_version={hash_version} doesn't exist")

    def _get_integrity_hash_fields_and_subfields(self):
        return self._get_integrity_hash_fields() + [
            f"line_ids.{subfield}"
            for subfield in self.line_ids._get_integrity_hash_fields()
        ]

    @api.model
    def _get_move_hash_domain(self, common_domain=False, force_hash=False):
        """
        Returns a search domain on model account.move checking whether they should be hashed.
        :param common_domain: a search domain that will be included in the returned domain in any case
        :param force_hash: if True, we'll check all moves posted, independently of journal settings
        """
        domain = Domain(common_domain or Domain.TRUE) & Domain("state", "=", "posted")
        if force_hash:
            return domain
        return domain & Domain("restrict_mode_hash_table", "=", True)

    @api.model
    def _is_move_restricted(self, move, force_hash=False):
        """
        Returns whether a move should be hashed (depending on journal settings)
        :param move: the account.move we check
        :param force_hash: if True, we'll check all moves posted, independently of journal settings
        """
        return move.filtered_domain(self._get_move_hash_domain(force_hash=force_hash))

    def _hash_moves(self, **kwargs):
        chains_to_hash = self._get_chains_to_hash(**kwargs)
        grant_secure_group_access = False
        for chain in chains_to_hash:
            move_hashes = (
                chain["moves"].sudo()._calculate_hashes(chain["previous_hash"])
            )
            for move, move_hash in move_hashes.items():
                # Bypass account.move.write(): a purely technical field write
                # cannot affect balance or business sync, and the secure
                # entries wizard hashes thousands of moves — one full
                # validation/sync pipeline per move is prohibitive.
                super(AccountMoveMain, move).write({"inalterable_hash": move_hash})
            # If any secured entries belong to journals without 'hash on post', the user should be granted access rights
            if not chain["journal_restrict_mode"]:
                grant_secure_group_access = True
            chain["moves"]._message_log_batch(
                bodies={
                    m.id: self.env._("This journal entry has been secured.")
                    for m in chain["moves"]
                }
            )
        if grant_secure_group_access:
            self.env["res.groups"]._activate_group_account_secured()

    def _get_chain_info(
        self, force_hash=False, include_pre_last_hash=False, early_stop=False
    ):
        """All records in `self` must belong to the same journal and sequence_prefix"""
        if not self:
            return False

        # Delegate to the database, instead of max(self, key=lambda m: m.sequence_number)
        last_move_in_chain = (
            self.env["account.move"]
            .sudo()
            .search_fetch(
                domain=[("id", "in", self.ids)],
                field_names=[
                    "sequence_prefix",
                    "sequence_number",
                    "journal_id",
                    # Pre-emptive fetching for `_is_move_restricted`
                    "state",
                    "restrict_mode_hash_table",
                ],
                order="sequence_number desc",
                limit=1,
            )
        )
        journal = last_move_in_chain.journal_id
        if not self._is_move_restricted(last_move_in_chain, force_hash=force_hash):
            return False

        common_domain = [
            ("journal_id", "=", journal.id),
            ("sequence_prefix", "=", last_move_in_chain.sequence_prefix),
        ]
        # sudo() like every other chain query here: a record rule hiding the
        # last hashed move would silently chain new hashes from the wrong
        # ancestor, permanently corrupting the inalterability chain.
        last_move_hashed = (
            self.env["account.move"]
            .sudo()
            .search_fetch(
                [
                    *common_domain,
                    ("inalterable_hash", "!=", False),
                ],
                ["sequence_number", "inalterable_hash"],
                order="sequence_number desc",
                limit=1,
            )
        )

        domain = self.env["account.move"]._get_move_hash_domain(
            [
                *common_domain,
                ("sequence_number", "<=", last_move_in_chain.sequence_number),
                ("inalterable_hash", "=", False),
            ],
            force_hash=True,
        )
        if last_move_hashed and not include_pre_last_hash:
            # Hash moves only after the last hashed move, not the ones that may have been posted before the journal was set on restrict mode
            domain &= Domain("sequence_number", ">", last_move_hashed.sequence_number)

        # On the accounting dashboard, we are only interested on whether there are documents to hash or not
        # so we can stop the computation early if we find at least one document to hash
        if early_stop:
            return self.env["account.move"].sudo().search_count(domain, limit=1)
        moves_to_hash = (
            self.env["account.move"]
            .sudo()
            .search_fetch(domain, ["sequence_number"], order="sequence_number")
        )
        info = {
            "previous_hash": last_move_hashed.inalterable_hash,
            "last_move_hashed": last_move_hashed,
        }
        if self.env.context.get("chain_info_warnings", True):
            warnings = set()
            if moves_to_hash:
                # Gap warning. `moves_to_hash` is ordered by sequence_number, so
                # a well-formed chain segment is exactly the contiguous range
                # [start, ..., last] with no missing numbers AND no duplicates.
                # Comparing count-vs-range instead (the previous approach) missed
                # a gap whenever a duplicate sequence number padded the count
                # back to the span, and mis-fired when `include_pre_last_hash`
                # pulled in moves numbered before `last_move_hashed`.
                seq_numbers = moves_to_hash.mapped("sequence_number")
                if last_move_hashed and not include_pre_last_hash:
                    start = last_move_hashed.sequence_number + 1
                else:
                    start = seq_numbers[0]
                if seq_numbers != list(range(start, seq_numbers[-1] + 1)):
                    warnings.add("gap")

                # unreconciled warning
                has_unreconciled = bool(
                    self.env["account.bank.statement.line"].search_count(
                        [
                            ("move_id", "in", moves_to_hash.ids),
                            ("is_reconciled", "=", False),
                        ],
                        limit=1,
                    )
                )
                if has_unreconciled:
                    warnings.add("unreconciled")
            else:
                warnings.add("no_document")

            info["warnings"] = warnings

        moves = moves_to_hash.sudo(False)
        info.update(
            {
                "moves": moves,
                "remaining_moves": self - moves,
            }
        )
        return info

    def _get_chains_to_hash(
        self,
        force_hash=False,
        raise_if_gap=True,
        raise_if_no_document=True,
        raise_if_unreconciled=True,
        include_pre_last_hash=False,
        early_stop=False,
    ):
        """
        From a recordset of moves, retrieve the chains of moves that need to be hashed by taking
        into account the last move of each chain of the recordset.
        So if we have INV/1, INV/2, INV/3, INV4 that are not hashed yet in the database
        but self contains INV/2, INV/3, we will return INV/1, INV/2 and INV/3. Not INV/4.
        :param force_hash: if True, we'll check all moves posted, independently of journal settings
        :param raise_if_gap: if True, we'll raise an error if a gap is detected in the sequence
        :param raise_if_no_document: if True, we'll raise an error if no document needs to be hashed
        :param raise_if_unreconciled: if True, we'll raise an error if an unreconciled statement line is found
        :param include_pre_last_hash: if True, we'll include the moves not hashed that are previous to the last hashed move
        :param early_stop: if True, we'll stop the computation as soon as we find at least one document to hash
        :return bool when early_stop else a list of dictionaries (each dict generated by `_get_chain_info`)
        """
        res = []
        for journal, journal_moves in self.grouped("journal_id").items():
            for chain_moves in journal_moves.grouped("sequence_prefix").values():
                chain_info = chain_moves._get_chain_info(
                    force_hash=force_hash,
                    include_pre_last_hash=include_pre_last_hash,
                    early_stop=early_stop,
                )

                if not chain_info:
                    continue
                if early_stop:
                    return True
                chain_info["journal_restrict_mode"] = journal.restrict_mode_hash_table

                # .get(): _get_chain_info omits "warnings" entirely under
                # chain_info_warnings=False in the context.
                warnings = chain_info.get("warnings") or set()
                if raise_if_unreconciled and "unreconciled" in warnings:
                    raise UserError(
                        _(
                            "An error occurred when computing the inalterability. All entries have to be reconciled."
                        )
                    )

                if raise_if_no_document and "no_document" in warnings:
                    raise UserError(
                        _(
                            "This move could not be locked either because "
                            "some move with the same sequence prefix has a higher number. You may need to resequence it."
                        )
                    )
                if raise_if_gap and "gap" in warnings:
                    raise UserError(
                        _(
                            "An error occurred when computing the inalterability. A gap has been detected in the sequence."
                        )
                    )

                res.append(chain_info)
        if early_stop:
            return False
        return res

    def _calculate_hashes(self, previous_hash):
        """
        :return: dict of move_id: hash
        """
        hash_version = self.env.context.get("hash_version", MAX_HASH_VERSION)

        def _getattrstring(obj, field_name):
            field_value = obj[field_name]
            if obj._fields[field_name].type == "many2one":
                field_value = field_value.id
            if obj._fields[field_name].type == "monetary" and hash_version >= 3:
                return float_repr(field_value, obj.currency_id.decimal_places)
            return str(field_value)

        move2hash = {}
        previous_hash = previous_hash or ""

        for move in self:
            if previous_hash and previous_hash.startswith("$"):
                previous_hash = previous_hash.split("$")[
                    2
                ]  # The hash version is not used for the computation of the next hash
            values = {}
            for fname in move._get_integrity_hash_fields():
                values[fname] = _getattrstring(move, fname)

            for line in move.line_ids:
                for fname in line._get_integrity_hash_fields():
                    k = "line_%d_%s" % (line.id, fname)
                    values[k] = _getattrstring(line, fname)
            current_record = dumps(
                values,
                sort_keys=True,
                ensure_ascii=True,
                indent=None,
                separators=(",", ":"),
            )
            hash_string = sha256(
                (previous_hash + current_record).encode("utf-8")
            ).hexdigest()
            move2hash[move] = (
                f"${hash_version}${hash_string}" if hash_version >= 4 else hash_string
            )
            previous_hash = move2hash[move]
        return move2hash
