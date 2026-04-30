from datetime import datetime, date
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, BankReconciliation, FinancialYear, Transaction, log_action

reconciliation_bp = Blueprint('reconciliation', __name__, url_prefix='/reconciliation')

MONTH_NAMES = BankReconciliation.MONTH_NAMES


@reconciliation_bp.route('/')
@login_required
def index():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    recons = BankReconciliation.query.filter_by(
        financial_year_id=fy.id
    ).order_by(BankReconciliation.year, BankReconciliation.month).all()

    return render_template('reconciliation/index.html', fy=fy, recons=recons)


@reconciliation_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can create reconciliations.', 'danger')
        return redirect(url_for('reconciliation.index'))

    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        month = request.form.get('month', '')
        year = request.form.get('year', '')
        opening_str = request.form.get('opening_balance', '').strip()
        closing_str = request.form.get('closing_balance', '').strip()
        outstanding_receipts_str = request.form.get('outstanding_receipts', '0').strip() or '0'
        outstanding_payments_str = request.form.get('outstanding_payments', '0').strip() or '0'
        notes = request.form.get('notes', '').strip()

        errors = []
        if not month.isdigit() or not (1 <= int(month) <= 12):
            errors.append('Please select a valid month.')
        if not year.isdigit():
            errors.append('Please select a valid year.')

        try:
            opening = Decimal(opening_str)
        except Exception:
            errors.append('Opening balance must be a valid number.')
            opening = Decimal('0')

        try:
            closing = Decimal(closing_str)
        except Exception:
            errors.append('Closing balance must be a valid number.')
            closing = Decimal('0')

        try:
            o_receipts = Decimal(outstanding_receipts_str)
            if o_receipts < 0:
                errors.append('Outstanding receipts cannot be negative.')
        except Exception:
            errors.append('Outstanding receipts must be a valid number.')
            o_receipts = Decimal('0')

        try:
            o_payments = Decimal(outstanding_payments_str)
            if o_payments < 0:
                errors.append('Outstanding payments cannot be negative.')
        except Exception:
            errors.append('Outstanding payments must be a valid number.')
            o_payments = Decimal('0')

        if not errors:
            mo, yr = int(month), int(year)
            existing = BankReconciliation.query.filter_by(
                financial_year_id=fy.id, month=mo, year=yr
            ).first()
            if existing:
                errors.append(f'A reconciliation for {MONTH_NAMES[mo]} {yr} already exists.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('reconciliation/form.html', fy=fy, form=request.form,
                                   is_new=True)

        recon = BankReconciliation(
            financial_year_id=fy.id,
            month=int(month),
            year=int(year),
            opening_balance=opening,
            closing_balance=closing,
            outstanding_receipts=o_receipts,
            outstanding_payments=o_payments,
            notes=notes,
            created_by_id=current_user.id,
        )
        db.session.add(recon)
        db.session.flush()
        log_action(current_user.id, 'reconciliation', 'create',
                   f'Created reconciliation for {MONTH_NAMES[int(month)]} {year}',
                   entity_id=recon.id)
        db.session.commit()
        flash(f'Reconciliation for {MONTH_NAMES[int(month)]} {year} saved.', 'success')
        return redirect(url_for('reconciliation.view', recon_id=recon.id))

    today = date.today()
    return render_template('reconciliation/form.html', fy=fy,
                           form={'month': today.month, 'year': today.year},
                           is_new=True)


@reconciliation_bp.route('/<int:recon_id>')
@login_required
def view(recon_id):
    recon = db.get_or_404(BankReconciliation, recon_id)
    fy = recon.financial_year
    # Cashbook totals for the reconciliation month
    import calendar
    mo, yr = recon.month, recon.year
    month_start = date(yr, mo, 1)
    month_end = date(yr, mo, calendar.monthrange(yr, mo)[1])
    month_txns = Transaction.query.filter(
        Transaction.financial_year_id == fy.id,
        Transaction.is_void == False,
        Transaction.date >= month_start,
        Transaction.date <= month_end,
    ).order_by(Transaction.date, Transaction.id).all()
    cashbook_receipts = sum(t.gross_amount for t in month_txns if t.transaction_type == 'receipt')
    cashbook_payments = sum(t.gross_amount for t in month_txns if t.transaction_type == 'payment')
    return render_template('reconciliation/view.html', recon=recon, fy=fy,
                           month_txns=month_txns,
                           cashbook_receipts=cashbook_receipts,
                           cashbook_payments=cashbook_payments)


@reconciliation_bp.route('/<int:recon_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(recon_id):
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can edit reconciliations.', 'danger')
        return redirect(url_for('reconciliation.index'))

    recon = db.get_or_404(BankReconciliation, recon_id)
    if recon.is_complete:
        flash('This reconciliation has been signed off and cannot be edited.', 'warning')
        return redirect(url_for('reconciliation.view', recon_id=recon_id))

    fy = recon.financial_year

    if request.method == 'POST':
        errors = []
        try:
            opening = Decimal(request.form.get('opening_balance', '').strip())
        except Exception:
            errors.append('Opening balance must be a valid number.')
            opening = recon.opening_balance

        try:
            closing = Decimal(request.form.get('closing_balance', '').strip())
        except Exception:
            errors.append('Closing balance must be a valid number.')
            closing = recon.closing_balance

        try:
            o_receipts = Decimal(request.form.get('outstanding_receipts', '0').strip() or '0')
        except Exception:
            errors.append('Outstanding receipts must be a valid number.')
            o_receipts = recon.outstanding_receipts

        try:
            o_payments = Decimal(request.form.get('outstanding_payments', '0').strip() or '0')
        except Exception:
            errors.append('Outstanding payments must be a valid number.')
            o_payments = recon.outstanding_payments

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('reconciliation/form.html', fy=fy, recon=recon,
                                   form=request.form, is_new=False)

        before = {'opening': str(recon.opening_balance), 'closing': str(recon.closing_balance)}
        recon.opening_balance = opening
        recon.closing_balance = closing
        recon.outstanding_receipts = o_receipts
        recon.outstanding_payments = o_payments
        recon.notes = request.form.get('notes', '').strip()
        recon.updated_at = datetime.utcnow()
        log_action(current_user.id, 'reconciliation', 'update',
                   f'Updated reconciliation for {recon.label}',
                   entity_id=recon.id, before=before,
                   after={'opening': str(opening), 'closing': str(closing)})
        db.session.commit()
        flash('Reconciliation updated.', 'success')
        return redirect(url_for('reconciliation.view', recon_id=recon_id))

    return render_template('reconciliation/form.html', fy=fy, recon=recon,
                           form=recon, is_new=False)


@reconciliation_bp.route('/<int:recon_id>/sign-off', methods=['POST'])
@login_required
def sign_off(recon_id):
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can sign off reconciliations.', 'danger')
        return redirect(url_for('reconciliation.index'))

    recon = db.get_or_404(BankReconciliation, recon_id)
    if recon.is_complete:
        flash('Already signed off.', 'warning')
        return redirect(url_for('reconciliation.view', recon_id=recon_id))

    if not recon.is_balanced:
        flash(
            f'Cannot sign off — reconciliation difference is £{recon.difference:,.2f}. '
            'The difference must be £0.00 before signing off.',
            'danger'
        )
        return redirect(url_for('reconciliation.view', recon_id=recon_id))

    recon.is_complete = True
    recon.signed_off_by_id = current_user.id
    recon.signed_off_at = datetime.utcnow()
    log_action(current_user.id, 'reconciliation', 'sign_off',
               f'Signed off reconciliation for {recon.label}', entity_id=recon.id)
    db.session.commit()
    flash(f'Reconciliation for {recon.label} signed off successfully.', 'success')
    return redirect(url_for('reconciliation.view', recon_id=recon_id))
