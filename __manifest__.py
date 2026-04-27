# -*- coding: utf-8 -*-
{
    "name": "Elks Treasurer — Refund Requests & Disbursements",
    "version": "19.0.1.1",
    "category": "Elks Lodge/Finance",
    "summary": "Process refund requests with Board/Floor approval and "
               "auto-generated journal entries.",
    "description": """
Elks Treasurer Module
======================

Gives the lodge Treasurer a workflow for processing refund and
disbursement requests.

Features
--------
* Enter refund requests with payee, reason, amount, and GL account
* Board → Floor approval workflow (same pattern as Purchase Orders)
* Auto-create journal entry on final approval (debit expense, credit
  cash/bank journal selected by the Treasurer)
* Branded PDF refund slip with Elks logos for record-keeping
* Full chatter / mail tracking on every request
""",
    "author": "Danny Santiago",
    "website": "https://dannysantiago.info",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "elksfrs",
    ],
    "data": [
        "security/elkstreasurer_groups.xml",
        "security/ir.model.access.csv",
        "report/refund_slip_report.xml",
        "views/refund_request_views.xml",
        "views/elkstreasurer_menus.xml",
    ],
    "installable": True,
    "application": True,
}
