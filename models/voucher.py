# -*- coding: utf-8 -*-
"""Payment Voucher — authorizes a check or expense payment.

Used when the lodge wants to issue a check for a sponsorship, donation,
expense reimbursement, or any disbursement that is NOT a refund.  The
printable Voucher tells the bookkeeper exactly who to pay, how much,
and which GL account to charge.

Workflow mirrors RefundRequest:
  Draft → Board Review → Floor Vote → Approved → Posted (JE created).
"""
import datetime
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

VOUCHER_STATES = [
    ('draft', 'Draft'),
    ('board', 'Board Review'),
    ('floor', 'Floor Vote'),
    ('approved', 'Approved'),
    ('posted', 'Posted'),
    ('rejected', 'Rejected'),
]

VOUCHER_TYPES = [
    ('sponsorship', 'Sponsorship'),
    ('donation', 'Donation'),
    ('expense', 'Expense / Reimbursement'),
    ('dues', 'Dues / Assessments'),
    ('utility', 'Utility / Service'),
    ('supply', 'Supplies'),
    ('other', 'Other'),
]


class ElksVoucher(models.Model):
    _name = "elks.voucher"
    _description = "Elks Payment Voucher"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "display_name"

    # ------------------------------------------------------------------
    # Core fields
    # ------------------------------------------------------------------
    name = fields.Char(
        "Voucher #", readonly=True, copy=False, default="New",
        help="Auto-assigned sequence number (VCH-YYYY-0001).",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    state = fields.Selection(
        VOUCHER_STATES, string="Status", default='draft',
        tracking=True, copy=False, index=True,
    )

    payee_id = fields.Many2one(
        "res.partner", string="Pay To", required=True,
        tracking=True,
        help="Person or organization receiving the payment.",
    )
    voucher_type = fields.Selection(
        VOUCHER_TYPES, string="Purpose", default='other',
        required=True, tracking=True,
        help="Categorize this voucher for reporting.",
    )
    memo = fields.Text(
        "Memo / Description", required=True, tracking=True,
        help="What the payment is for — this prints on the voucher "
             "and is used as the journal entry memo.",
    )
    amount = fields.Monetary(
        "Amount", required=True, tracking=True,
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
    date_needed = fields.Date(
        "Date Needed",
        help="When the check needs to be ready by.",
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
        "elks.account", string="Pay From Account",
        domain="[('account_type', 'in', ['bank', 'asset'])]",
        tracking=True,
        help="Elks COA cash or bank account to pay from "
             "(e.g. 10100 Cash, 10200 Checking).",
    )

    check_number = fields.Char(
        "Check Number", tracking=True,
        help="Filled in by the bookkeeper once the check is written.",
    )

    # Budget availability
    budget_line_id = fields.Many2one(
        "elks.budget.line", string="Budget Line",
        compute="_compute_budget_line", store=False,
    )
    budget_available = fields.Monetary(
        "Budget Available", compute="_compute_budget_available",
        currency_field='currency_id',
    )
    over_budget = fields.Boolean(
        "Over Budget", compute="_compute_budget_available",
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
        help="The Elks FRS journal entry created when the voucher is posted.",
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

    def _get_current_budget(self):
        """Return the active budget for the current Elk year (Apr-Mar)."""
        Budget = self.env.get('elks.budget')
        if Budget is None:
            return False
        today = datetime.date.today()
        fye = datetime.date(
            today.year + 1 if today.month >= 4 else today.year, 3, 31,
        )
        budget = Budget.search([
            ('fiscal_year_end', '=', fye),
            ('state', 'in', (
                'board_pending', 'board_approved',
                'floor_pending', 'floor_approved',
                'approved', 'submitted',
            )),
        ], limit=1)
        if not budget:
            budget = Budget.search([
                ('fiscal_year_end', '=', fye),
            ], limit=1)
        return budget

    @api.depends("elks_account_id")
    def _compute_budget_line(self):
        """Auto-resolve the budget line from the GL account."""
        budget = self._get_current_budget()
        BudgetLine = self.env.get('elks.budget.line')
        for rec in self:
            if rec.elks_account_id and budget and BudgetLine:
                bl = BudgetLine.search([
                    ('budget_id', '=', budget.id),
                    ('account_id', '=', rec.elks_account_id.id),
                ], limit=1)
                rec.budget_line_id = bl.id if bl else False
            else:
                rec.budget_line_id = False

    @api.depends("budget_line_id", "amount")
    def _compute_budget_available(self):
        """Check how much budget remains for this GL account."""
        for rec in self:
            if rec.budget_line_id:
                bl = rec.budget_line_id
                if hasattr(bl, 'available_amount'):
                    rec.budget_available = bl.available_amount
                else:
                    rec.budget_available = bl.amount - bl.actual_amount
                rec.over_budget = rec.amount > rec.budget_available
            else:
                rec.budget_available = 0.0
                rec.over_budget = False

    @api.onchange("elks_account_id", "amount")
    def _onchange_check_budget(self):
        """Warn user if this voucher exceeds the available budget."""
        if self.over_budget and self.budget_line_id:
            return {
                'warning': {
                    'title': _("Over Budget"),
                    'message': _(
                        "This voucher ($%(amount)s) exceeds the available "
                        "budget for %(account)s.\n\n"
                        "Budget available: $%(available)s\n"
                        "Shortfall: $%(shortfall)s\n\n"
                        "You can still submit this voucher, but a budget "
                        "transfer may be needed before approval.",
                        amount=f"{self.amount:,.2f}",
                        account=self.elks_account_id.display_name,
                        available=f"{self.budget_available:,.2f}",
                        shortfall=f"{self.amount - self.budget_available:,.2f}",
                    ),
                }
            }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'elks.voucher'
                ) or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_submit_to_board(self):
        """Submit the voucher for Board review."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft vouchers can be submitted."))
            if rec.amount <= 0:
                raise UserError(_("Amount must be greater than zero."))
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
                    "This voucher is not in the Board review queue."
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
        """Board rejects the voucher."""
        for rec in self:
            if rec.state != 'board':
                raise UserError(_(
                    "This voucher is not in the Board review queue."
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
                    "This voucher is not in the Floor vote queue."
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
        """Floor rejects the voucher."""
        for rec in self:
            if rec.state != 'floor':
                raise UserError(_(
                    "This voucher is not in the Floor vote queue."
                ))
            rec.state = 'rejected'
            rec.message_post(
                body=_("<b>Rejected by Floor</b> — %s.", self.env.user.name),
                subtype_xmlid='mail.mt_comment',
            )

    def action_post(self):
        """Post the voucher — create the Elks FRS journal entry."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_(
                    "Only approved vouchers can be posted."
                ))
            if not rec.payment_account_id:
                raise UserError(_(
                    "Please select a Pay From Account (Cash or Bank) "
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
        """Reset a rejected voucher back to draft."""
        for rec in self:
            if rec.state != 'rejected':
                raise UserError(_(
                    "Only rejected vouchers can be reset to draft."
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

    def action_print_voucher(self):
        """Preview the voucher (HTML)."""
        self.ensure_one()
        return self.env.ref(
            'elkstreasurer.action_report_voucher'
        ).report_action(self)

    def action_download_voucher_pdf(self):
        """Download the voucher as PDF."""
        self.ensure_one()
        return self.env.ref(
            'elkstreasurer.action_report_voucher_pdf'
        ).report_action(self)

    # ------------------------------------------------------------------
    # Journal entry creation
    # ------------------------------------------------------------------
    def _create_journal_entry(self):
        """Create an Elks FRS journal entry: debit expense, credit cash/bank."""
        self.ensure_one()
        if self.journal_entry_id:
            raise UserError(_(
                "A journal entry already exists for this voucher."
            ))

        JE = self.env['elks.journal.entry']
        memo_short = (self.memo or '')[:80]
        type_label = dict(VOUCHER_TYPES).get(self.voucher_type, '')

        entry = JE.create({
            'date': fields.Date.context_today(self),
            'memo': f"Voucher {self.name} — {self.payee_id.name}"
                    f" ({type_label}): {memo_short}",
            'line_ids': [
                (0, 0, {
                    'account_id': self.elks_account_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'memo': f"{type_label}: {memo_short}",
                }),
                (0, 0, {
                    'account_id': self.payment_account_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                    'memo': f"Voucher {self.name}"
                            f"{' — Check #' + self.check_number if self.check_number else ''}",
                }),
            ],
        })
        entry.action_post()
        self.journal_entry_id = entry.id
        _logger.info(
            "Created and posted Elks journal entry %s for voucher %s ($%.2f)",
            entry.name, self.name, self.amount,
        )
