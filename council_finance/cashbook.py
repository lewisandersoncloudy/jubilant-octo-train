from datetime import datetime, date
from decimal import Decimal
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, current_app)
from flask_login import login_required, current_user
from .models import (db, Transaction, BudgetHeading, FinancialYear,
                     BankAccount, Grant, log_action)

cashbook_bp = Blueprint('cashbook', __name__, url_prefix='/cashbook')


@cashbook_bp.route('/')
@login_required
def index():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year is configured.', 'warning')
        return redirect(url_for('dashboard'))

    txn_type = request.args.get('type', '')
    heading_id = request.args.get('heading', '')
    month = request.args.get('month', '')
    bank_id = request.args.get('bank', '')
    show_void = request.args.get('show_void', '') == '1'
    s137_only = request.args.get('s137', '') == '1'

    query = Transaction.query.filter_by(financial_year_id=fy.id)
    if not show_void:
        query = query.filter_by(is_void=False)
    if txn_type in ('receipt', 'payment'):
        query = query.filter_by(transaction_type=txn_type)
    if heading_id.isdigit():
        query = query.filter_by(budget_heading_id=int(heading_id))
    if month.isdigit():
        from sqlalchemy import extract
        query = query.filter(extract('month', Transaction.date) == int(month))
    if bank_id.isdigit():
        query = query.filter_by(bank_account_id=int(bank_id))
    if s137_only:
        query = query.filter_by(section_137=True)

    transactions = query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()

    active = [t for t in transactions if not t.is_void]
    total_receipts = sum(t.gross_amount for t in active if t.transaction_type == 'receipt')
    total_payments = sum(t.gross_amount for t in active if t.transaction_type == 'payment')

    return render_template('cashbook/index.html',
                           fy=fy, transactions=transactions,
                           headings=headings, bank_accounts=bank_accounts,
                           total_receipts=total_receipts, total_payments=total_payments,
                           filter_type=txn_type, filter_heading=heading_id,
                           filter_month=month, filter_bank=bank_id,
                           show_void=show_void, s137_only=s137_only)


@cashbook_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can add transactions.', 'danger')
        return redirect(url_for('cashbook.index'))

    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(
        BankAccount.is_primary.desc(), BankAccount.name
    ).all()
    grants = Grant.query.filter_by(is_active=True).order_by(Grant.name).all()

    if request.method == 'POST':
        txn_type = request.form.get('transaction_type', '')
        date_str = request.form.get('date', '')
        reference = request.form.get('reference', '').strip()
        payee_payer = request.form.get('payee_payer', '').strip()
        description = request.form.get('description', '').strip()
        heading_id = request.form.get('budget_heading_id', '')
        bank_account_id = request.form.get('bank_account_id', '') or None
        net_str = request.form.get('net_amount', '').strip()
        vat_str = request.form.get('vat_amount', '0').strip() or '0'
        vat_reclaimable = request.form.get('vat_reclaimable') == '1'
        section_137 = request.form.get('section_137') == '1'
        grant_id = request.form.get('grant_id', '') or None
        notes = request.form.get('notes', '').strip()

        errors = []
        if txn_type not in ('receipt', 'payment'):
            errors.append('Please select Receipt or Payment.')
        if not reference:
            errors.append('Reference is required.')
        if not payee_payer:
            errors.append('Payee / Payer is required.')
        if not description:
            errors.append('Description is required.')
        if not heading_id.isdigit():
            errors.append('Budget heading is required.')

        try:
            net_amount = Decimal(net_str)
            if net_amount <= 0:
                errors.append('Net amount must be greater than zero.')
        except Exception:
            errors.append('Net amount must be a valid number.')
            net_amount = Decimal('0')

        try:
            vat_amount = Decimal(vat_str)
            if vat_amount < 0:
                errors.append('VAT amount cannot be negative.')
        except Exception:
            errors.append('VAT amount must be a valid number.')
            vat_amount = Decimal('0')

        try:
            txn_date = date.fromisoformat(date_str)
            if txn_date < fy.start_date or txn_date > fy.end_date:
                errors.append(f'Date must be within {fy.label}.')
        except (ValueError, AttributeError):
            errors.append('Invalid date.')
            txn_date = date.today()

        if heading_id.isdigit():
            heading = BudgetHeading.query.get(int(heading_id))
            if heading and heading.category not in (txn_type + 's', txn_type):
                # allow flexible category matching
                if heading.is_income and txn_type == 'payment':
                    errors.append(f'"{heading.name}" is an income heading — choose a payments heading.')
                elif not heading.is_income and txn_type == 'receipt':
                    errors.append(f'"{heading.name}" is a payments heading — choose an income heading.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('cashbook/add.html', fy=fy, headings=headings,
                                   bank_accounts=bank_accounts, grants=grants,
                                   form=request.form)

        txn = Transaction(
            financial_year_id=fy.id,
            bank_account_id=int(bank_account_id) if bank_account_id and str(bank_account_id).isdigit() else None,
            date=txn_date,
            reference=reference,
            payee_payer=payee_payer,
            description=description,
            budget_heading_id=int(heading_id),
            transaction_type=txn_type,
            net_amount=net_amount,
            vat_amount=vat_amount,
            vat_reclaimable=vat_reclaimable,
            section_137=section_137,
            grant_id=int(grant_id) if grant_id and str(grant_id).isdigit() else None,
            notes=notes,
            created_by_id=current_user.id,
        )
        db.session.add(txn)
        db.session.flush()  # get txn.id before upload

        # ── SharePoint document upload ──────────────────────────────────────
        uploaded_file = request.files.get('document')
        if uploaded_file and uploaded_file.filename:
            from . import sharepoint as sp
            try:
                file_bytes = uploaded_file.read()
                web_url, stored_name = sp.upload_document(txn, file_bytes, uploaded_file.filename)
                txn.document_url = web_url
                txn.document_filename = stored_name
                flash(f'Document "{stored_name}" uploaded to SharePoint.', 'info')
            except Exception as exc:
                flash(f'Transaction saved but document upload failed: {exc}', 'warning')

        log_action(current_user.id, 'transaction', 'create',
                   f'Added {txn_type} £{net_amount:,.2f} — {payee_payer} — {description}',
                   entity_id=txn.id,
                   after={'date': str(txn_date), 'reference': reference,
                          'payee_payer': payee_payer, 'net_amount': str(net_amount),
                          'vat_amount': str(vat_amount), 'type': txn_type,
                          'section_137': section_137})
        db.session.commit()
        flash(f'{txn_type.capitalize()} of £{net_amount:,.2f} added successfully.', 'success')
        return redirect(url_for('cashbook.index'))

    return render_template('cashbook/add.html', fy=fy, headings=headings,
                           bank_accounts=bank_accounts, grants=grants, form={})


@cashbook_bp.route('/<int:txn_id>/void', methods=['GET', 'POST'])
@login_required
def void_transaction(txn_id):
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can void transactions.', 'danger')
        return redirect(url_for('cashbook.index'))

    txn = db.get_or_404(Transaction, txn_id)
    if txn.is_void:
        flash('This transaction is already void.', 'warning')
        return redirect(url_for('cashbook.index'))

    if request.method == 'POST':
        reason = request.form.get('void_reason', '').strip()
        if not reason:
            flash('A reason for voiding is required.', 'danger')
            return render_template('cashbook/void.html', txn=txn)

        before = {'date': str(txn.date), 'payee_payer': txn.payee_payer,
                  'net_amount': str(txn.net_amount), 'is_void': False}
        txn.is_void = True
        txn.void_reason = reason
        txn.void_at = datetime.utcnow()
        txn.void_by_id = current_user.id

        log_action(current_user.id, 'transaction', 'void',
                   f'Voided {txn.reference} — {txn.payee_payer}',
                   entity_id=txn.id, reason=reason,
                   before=before, after={'is_void': True, 'void_reason': reason})
        db.session.commit()
        flash(f'Transaction {txn.reference} has been voided.', 'success')
        return redirect(url_for('cashbook.index'))

    return render_template('cashbook/void.html', txn=txn)
