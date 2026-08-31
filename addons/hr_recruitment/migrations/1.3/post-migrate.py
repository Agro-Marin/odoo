r"""Post-migration: applicant property definitions move from the job to the company.

``hr.applicant.applicant_properties`` used to resolve its definition through
``job_id``, which left a talent -- created without a job -- and a spontaneous
application unable to hold any property at all. The definition now hangs off
``company_id``, the shape ``hr.employee`` already uses.

The values themselves live in a jsonb column on ``hr_applicant`` and resolve by
property name, so they survive the move as long as the company's definition
declares the same names. That is what this script guarantees: every definition
configured on a job is folded into the definition of that job's company, keyed
by name, first one wins on a clash between two jobs of the same company.

``hr.job.applicant_properties_definition`` is deliberately left in place rather
than dropped, so a definition is never destroyed by an upgrade that runs before
anyone has looked at the result.

Idempotent: a name already present in the company's definition is not written
again, so a second run folds nothing.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Fold every job's applicant property definition into its company's.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    jobs = env["hr.job"].search([("applicant_properties_definition", "!=", False)])
    if not jobs:
        return

    for company, company_jobs in jobs.grouped("company_id").items():
        target = company or env["res.company"].browse(env.ref("base.main_company").id)
        definition = list(target.applicant_properties_definition or [])
        known = {prop["name"] for prop in definition}
        for job in company_jobs:
            for prop in job.applicant_properties_definition or []:
                if prop["name"] not in known:
                    definition.append(prop)
                    known.add(prop["name"])
        target.applicant_properties_definition = definition
