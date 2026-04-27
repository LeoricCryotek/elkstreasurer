# -*- coding: utf-8 -*-
"""Refund / Disbursement Request with Board → Floor approval workflow.

Follows the same approval pattern as elkspurchase:
Draft → Board → Floor → Approved → Posted (journal entry created).
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REFUND_STATES = [
    ('draft', 'Draft'),
    ('board', 'Board Review'),
    ('floor', 'Floor Vote'),
    ('approved', 'Approved'),
    ('posted', 'Posted'),
    ('rejected', 'Rejected'),
]


class ElksRefundRequest(models.Model):
    _name = "elks.refund.request"
    _description = "Elks Refund / Disbursement Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "display_name"

    # ------------------------------------------------------------------
    # Core fields
    # ------------------------------------------------------------------
    name = fields.Char(
        "Reference", readonly=True, copy=False, default="New",
        help="Auto-assigned sequence number.",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    state = fields.Selection(
        REFUND_STATES, string="Status", default='draft',
        tracking=True, copy=False, index=True,
    )

    payee_id = fields.Many2one(
        "res.partner", string="Payee", required=True,
        tracking=True,
        help="Person or vendor receiving the refund.",
    )
    reason = fields.Text(
        "Reason / Description", required=True, tracking=True,
        help="Why the refund is being issued.",
    )
    amount = fields.Monetary(
        "Refund Amount", required=True, tracking=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    request_date = fields.Date(
        "Request Date", default=fields.Date.context_today,
        tracking=True,
    )
    requested_by = fields.Many2one(
        "res.users", string="Requested By",
        default=lambda self: self.env.user,
        tracking=True,
    )

    # GL Account from FRS
    elks_account_id = fields.Many2one(
        "elks.account", string="GL Expense Account",
        required=True, tracking=True,
        domain="[('account_type', 'in', ['expense', 'cogs'])]",
        help="Elks Chart of Accounts expense line to charge.",
    )
    elks_department_id = fields.Many2one(
        "elks.department", string="Elks Department",
        related="elks_account_id.department_id", store=True,
    )

    # Payment source account from Elks COA (Cash or Bank)
    payment_account_id = fields.Many2one(
        "elks.account", string="Payment Account",
        domain="[('account_type', 'in', ['bank', 'asset'])]",
        tracking=True,
        help="Elks COA cash or bank account to pay the refund from "
             "(e.g. 10100 Cash, 10200 Checking).",
    )

    # Approval tracking
    board_approved_by = fields.Many2one(
        "res.users", string="Board Approved By",
        readonly=True, copy=False,
    )
    board_approved_on = fields.Datetime(
        "Board Approved On", readonly=True, copy=False,
    )
    floor_approved_by = fields.Many2one(
        "res.users", string="Floor Approved By",
        readonly=True, copy=False,
    )
    floor_approved_on = fields.Datetime(
        "Floor Approved On", readonly=True, copy=False,
    )

    # Elks FRS journal entry link
    journal_entry_id = fields.Many2one(
        "elks.journal.entry", string="Journal Entry",
        readonly=True, copy=False,
        help="The Elks FRS journal entry created when the refund is posted.",
    )

    notes = fields.Html("Internal Notes")

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------
    @api.depends("name", "payee_id.name")
    def _compute_display_name(self):
        for rec in self:
            payee = rec.payee_id.name or "—"
            rec.display_name = f"{rec.name} — {payee}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'elks.refund.request'
                ) or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_submit_to_board(self):
        """Submit the refund request for Board review."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft requests can be submitted."))
            if rec.amount <= 0:
                raise UserError(_("Refund amount must be greater than zero."))
            rec.state = 'board'
            rec.message_post(
                body=_("Submitted to <b>Board</b> for review by %s.",
                       self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_board_approve(self):
        """Board approves — advance to Floor vote."""
        for rec in self:
            if rec.state != 'board':
                raise UserError(_(
                    "This request is not in the Board review queue."
                ))
            rec.write({
                'state': 'floor',
                'board_approved_by': self.env.user.id,
                'board_approved_on': fields.Datetime.now(),
            })
            rec.message_post(
                body=_("<b>Board Approved</b> by %s.", self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_board_reject(self):
        """Board rejects the request."""
        for rec in self:
            if rec.state != 'board':
                raise UserError(_(
                    "This request is not in the Board review queue."
                ))
            rec.state = 'rejected'
            rec.message_post(
                body=_("<b>Rejected by Board</b> — %s.", self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_floor_approve(self):
        """Floor approves — mark as Approved."""
        for rec in self:
            if rec.state != 'floor':
                raise UserError(_(
                    "This request is not in the Floor vote queue."
                ))
            rec.write({
                'state': 'approved',
                'floor_approved_by': self.env.user.id,
                'floor_approved_on': fields.Datetime.now(),
            })
            rec.message_post(
                body=_("<b>Floor Approved</b> — recorded by %s.",
                       self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_floor_reject(self):
        """Floor rejects the request."""
        for rec in self:
            if rec.state != 'floor':
                raise UserError(_(
                    "This request is not in the Floor vote queue."
                ))
            rec.state = 'rejected'
            rec.message_post(
                body=_("<b>Rejected by Floor</b> — %s.", self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_post(self):
        """Post the refund — create the Elks FRS journal entry."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_(
                    "Only approved requests can be posted."
                ))
            if not rec.payment_account_id:
                raise UserError(_(
                    "Please select a Payment Account (Cash or Bank) "
                    "before posting."
                ))
            rec._create_journal_entry()
            rec.state = 'posted'
            rec.message_post(
                body=_(
                    "<b>Posted</b> by %s.<br/>"
                    "Journal Entry: %s",
                    self.env.user.name,
                    rec.journal_entry_id.name or "—",
                ),
                subtype_xmlid='mail.mt_comment',
            )

    def action_reset_to_draft(self):
        """Reset a rejected request back to draft."""
        for rec in self:
            if rec.state != 'rejected':
                raise UserError(_(
                    "Only rejected requests can be reset to draft."
                ))
            rec.write({
                'state': 'draft',
                'board_approved_by': False,
                'board_approved_on': False,
                'floor_approved_by': False,
                'floor_approved_on': False,
            })
            rec.message_post(
                body=_("Reset to <b>Draft</b> by %s.", self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_print_slip(self):
        """Preview the refund slip (HTML)."""
        self.ensure_one()
        return self.env.ref(
            'elkstreasurer.action_report_refund_slip'
        ).report_action(self)

    def action_download_slip_pdf(self):
        """Download the refund slip as PDF."""
        self.ensure_one()
        return self.env.ref(
            'elkstreasurer.action_report_refund_slip_pdf'
        ).report_action(self)

    # ------------------------------------------------------------------
    # Journal entry creation
    # ------------------------------------------------------------------
    def _create_journal_entry(self):
        """Create an Elks FRS journal entry: debit expense, credit cash/bank."""
        self.ensure_one()
        if self.journal_entry_id:
            raise UserError(_(
                "A journal entry already exists for this refund."
            ))

        JE = self.env['elks.journal.entry']
        reason_short = (self.reason or '')[:80]

        entry = JE.create({
            'date': fields.Date.context_today(self),
            'memo': f"Refund {self.name} — {self.payee_id.name}: {reason_short}",
            'line_ids': [
                (0, 0, {
                    'account_id': self.elks_account_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'memo': f"Refund: {reason_short}",
                }),
                (0, 0, {
                    'account_id': self.payment_account_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                    'memo': f"Refund {self.name}",
                }),
            ],
        })
        entry.action_post()
        self.journal_entry_id = entry.id
        _logger.info(
            "Created and posted Elks journal entry %s for refund %s ($%.2f)",
            entry.name, self.name, self.amount,
        )
