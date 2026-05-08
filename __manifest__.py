# -*- coding: utf-8 -*-
{
    "name": "Elks Treasurer — Refund Requests & Payment Vouchers",
    "version": "19.0.1.2",
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
* Payment vouchers for sponsorships, donations, expenses
* Board → Floor approval workflow (same pattern as Purchase Orders)
* Auto-create journal entry on final approval (debit expense, credit
  cash/bank journal selected by the Treasurer)
* Branded PDF refund slip and payment voucher with Elks logos
* Check number tracking on vouchers
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
        "report/voucher_report.xml",
        "views/refund_request_views.xml",
        "views/voucher_views.xml",
        "views/elkstreasurer_menus.xml",
    ],
    "installable": True,
    "application": True,
}
