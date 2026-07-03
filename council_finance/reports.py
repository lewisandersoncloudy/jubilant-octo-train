"""
Reports and exports — Excel workbook, CSV, and printable HTML reports.
Supports both Receipts & Payments and Income & Expenditure accounting bases.
"""
import csv
import io
from decimal import Decimal
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, Response, send_file)
from flask_login import login_required
from .models import (FinancialYear, Transaction, BudgetHeading, Budget,
                     BankReconciliation, CouncilSettings, Asset, Accrual, Reserve)
from .budget import _rag_status

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


def _get_fy(fy_id=None):
    if fy_id:
        return FinancialYear.query.get(fy_id)
    return FinancialYear.query.filter_by(is_current=True).first()


def _build_budget_rows(fy):
    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    rows = []
    for h in headings:
        bobj = Budget.query.filter_by(financial_year_id=fy.id, budget_heading_id=h.id).first()
        budget_amt = Decimal(str(bobj.effective_amount)) if bobj else Decimal('0')
        spent = sum(
            Decimal(str(t.net_amount))
            for t in Transaction.query.filter_by(
                financial_year_id=fy.id, budget_heading_id=h.id, is_void=False
            ).all()
        )
        rows.append({
            'heading': h,
            'budget': budget_amt,
            'spent': spent,
            'remaining': budget_amt - spent,
            'rag': _rag_status(spent, budget_amt),
            'total': sum(
                Decimal(str(t.net_amount)) + Decimal(str(t.vat_amount))
                for t in Transaction.query.filter_by(
                    financial_year_id=fy.id, budget_heading_id=h.id, is_void=False
                ).all()
            ),
            'budget_obj': bobj,
        })
    return rows


@reports_bp.route('/')
@login_required
def index():
    years = FinancialYear.query.order_by(FinancialYear.start_date.desc()).all()
    settings = CouncilSettings.query.first()
    return render_template('reports/index.html', years=years, settings=settings)


# ── Excel workbook ────────────────────────────────────────────────────────────

@reports_bp.route('/workbook.xlsx')
@login_required
def excel_workbook():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('Financial year not found.', 'warning')
        return redirect(url_for('reports.index'))

    settings = CouncilSettings.query.first()
    transactions = Transaction.query.filter_by(financial_year_id=fy.id).order_by(
        Transaction.date, Transaction.id
    ).all()
    budget_rows = _build_budget_rows(fy)
    recons = BankReconciliation.query.filter_by(financial_year_id=fy.id).order_by(
        BankReconciliation.year, BankReconciliation.month
    ).all()

    vat_txns = Transaction.query.filter(
        Transaction.financial_year_id == fy.id,
        Transaction.is_void == False,
        Transaction.vat_amount > 0,
    ).order_by(Transaction.date, Transaction.id).all()

    receipts_vat = sum(Decimal(str(t.vat_amount)) for t in vat_txns if t.transaction_type == 'receipt')
    payments_vat = sum(Decimal(str(t.vat_amount)) for t in vat_txns if t.transaction_type == 'payment')
    reclaimable = sum(Decimal(str(t.vat_amount)) for t in vat_txns
                      if t.transaction_type == 'payment' and t.vat_reclaimable)
    vat_data = {
        'txns': vat_txns,
        'receipts_vat': receipts_vat,
        'payments_vat': payments_vat,
        'reclaimable': reclaimable,
        'net': reclaimable - receipts_vat,
    }

    assets = Asset.query.order_by(Asset.category, Asset.name).all()
    accruals = Accrual.query.filter_by(financial_year_id=fy.id).all()
    reserves = Reserve.query.filter_by(is_active=True).all()

    from .excel_export import build_workbook
    _, workbook_bytes = build_workbook(fy, settings, transactions, budget_rows,
                                       recons, vat_data, assets, accruals, reserves)

    label = fy.label.replace('/', '-')
    filename = f'Council_Finance_{label}_{datetime.today().strftime("%Y%m%d")}.xlsx'
    return send_file(
        io.BytesIO(workbook_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


# ── CSV exports ───────────────────────────────────────────────────────────────

@reports_bp.route('/cashbook.csv')
@login_required
def cashbook_csv():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    txns = Transaction.query.filter_by(financial_year_id=fy.id).order_by(
        Transaction.date, Transaction.id
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date', 'Reference', 'Type', 'Payee/Payer', 'Description',
        'Budget Heading', 'Net (£)', 'VAT (£)', 'Gross (£)',
        'VAT Reclaimable', 'Section 137', 'Bank Account', 'Document', 'Notes', 'Void',
    ])
    for t in txns:
        writer.writerow([
            t.date.strftime('%d/%m/%Y'), t.reference, t.type_label,
            t.payee_payer, t.description, t.heading.name,
            f'{t.net_amount:.2f}', f'{t.vat_amount:.2f}', f'{t.gross_amount:.2f}',
            'Yes' if t.vat_reclaimable else 'No',
            'Yes' if t.section_137 else 'No',
            t.bank_account.name if t.bank_account else '',
            t.document_filename or '',
            t.notes or '',
            'Yes' if t.is_void else 'No',
        ])

    label = fy.label.replace('/', '-')
    filename = f'cashbook_{label}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@reports_bp.route('/budget.csv')
@login_required
def budget_csv():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    rows = _build_budget_rows(fy)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Category', 'Heading', 'Budget (£)', 'Actual (£)', 'Variance (£)', '% Used', 'Notes'])
    for row in rows:
        pct = float(row['spent'] / row['budget'] * 100) if row['budget'] > 0 else 0
        note = ''
        if row['budget_obj'] and row['budget_obj'].adjusted_amount is not None:
            note = f'Adjusted: {row["budget_obj"].adjustment_note}'
        writer.writerow([
            row['heading'].category_label, row['heading'].name,
            f'{row["budget"]:.2f}', f'{row["spent"]:.2f}',
            f'{row["remaining"]:.2f}', f'{pct:.1f}%', note,
        ])

    label = fy.label.replace('/', '-')
    filename = f'budget_{label}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@reports_bp.route('/vat.csv')
@login_required
def vat_csv():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    vat_txns = Transaction.query.filter(
        Transaction.financial_year_id == fy.id,
        Transaction.is_void == False,
        Transaction.vat_amount > 0,
    ).order_by(Transaction.date, Transaction.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Reference', 'Type', 'Payee/Payer',
                     'Description', 'Net (£)', 'VAT (£)', 'Reclaimable'])
    for t in vat_txns:
        writer.writerow([
            t.date.strftime('%d/%m/%Y'), t.reference, t.type_label,
            t.payee_payer, t.description,
            f'{t.net_amount:.2f}', f'{t.vat_amount:.2f}',
            'Yes' if t.vat_reclaimable else 'No',
        ])

    label = fy.label.replace('/', '-')
    filename = f'vat126_{label}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@reports_bp.route('/section-137.csv')
@login_required
def section_137_csv():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    txns = Transaction.query.filter_by(
        financial_year_id=fy.id, is_void=False, section_137=True
    ).order_by(Transaction.date).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Reference', 'Payee', 'Description',
                     'Budget Heading', 'Net (£)', 'VAT (£)', 'Gross (£)'])
    total = Decimal('0')
    for t in txns:
        writer.writerow([
            t.date.strftime('%d/%m/%Y'), t.reference, t.payee_payer,
            t.description, t.heading.name,
            f'{t.net_amount:.2f}', f'{t.vat_amount:.2f}', f'{t.gross_amount:.2f}',
        ])
        total += t.gross_amount
    writer.writerow(['', '', '', '', 'TOTAL', '', '', f'{total:.2f}'])

    label = fy.label.replace('/', '-')
    filename = f's137_{label}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


# ── Printable HTML reports ────────────────────────────────────────────────────

@reports_bp.route('/receipts-and-payments')
@login_required
def receipts_and_payments():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    settings = CouncilSettings.query.first()
    rows = _build_budget_rows(fy)
    receipt_rows = [r for r in rows if r['heading'].is_income]
    payment_rows = [r for r in rows if not r['heading'].is_income]
    total_receipts = sum(r['total'] for r in receipt_rows)
    total_payments = sum(r['total'] for r in payment_rows)

    first_recon = BankReconciliation.query.filter_by(
        financial_year_id=fy.id, is_complete=True
    ).order_by(BankReconciliation.year, BankReconciliation.month).first()
    opening = Decimal(str(first_recon.opening_balance)) if first_recon else Decimal('0')

    return render_template('reports/receipts_and_payments.html',
                           fy=fy, settings=settings,
                           receipt_rows=receipt_rows, payment_rows=payment_rows,
                           total_receipts=total_receipts, total_payments=total_payments,
                           opening_balance=opening,
                           closing_balance=opening + total_receipts - total_payments,
                           net=total_receipts - total_payments,
                           generated=datetime.now())


@reports_bp.route('/income-expenditure')
@login_required
def income_expenditure():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    settings = CouncilSettings.query.first()
    rows = _build_budget_rows(fy)
    income_rows = [r for r in rows if r['heading'].is_income]
    expenditure_rows = [r for r in rows if not r['heading'].is_income]
    total_income = sum(r['total'] for r in income_rows)
    total_expenditure = sum(r['total'] for r in expenditure_rows)

    accruals = Accrual.query.filter_by(financial_year_id=fy.id, is_reversed=False).all()
    accrued_income = sum(Decimal(str(a.amount)) for a in accruals
                         if a.accrual_type in ('accrued_income', 'debtor'))
    prepayments = sum(Decimal(str(a.amount)) for a in accruals
                      if a.accrual_type == 'prepayment')
    accrued_exp = sum(Decimal(str(a.amount)) for a in accruals
                      if a.accrual_type in ('accrued_expenditure', 'creditor'))

    adj_income = total_income + accrued_income - prepayments
    adj_expenditure = total_expenditure + accrued_exp
    surplus = adj_income - adj_expenditure

    return render_template('reports/income_expenditure.html',
                           fy=fy, settings=settings,
                           income_rows=income_rows, expenditure_rows=expenditure_rows,
                           total_income=total_income, total_expenditure=total_expenditure,
                           accrued_income=accrued_income, prepayments=prepayments,
                           accrued_exp=accrued_exp,
                           adj_income=adj_income, adj_expenditure=adj_expenditure,
                           surplus=surplus,
                           accruals=accruals,
                           generated=datetime.now())


@reports_bp.route('/balance-sheet')
@login_required
def balance_sheet():
    fy_id = request.args.get('fy', type=int)
    fy = _get_fy(fy_id)
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    settings = CouncilSettings.query.first()
    assets = Asset.query.filter_by(is_disposed=False).order_by(Asset.category, Asset.name).all()
    accruals = Accrual.query.filter_by(financial_year_id=fy.id, is_reversed=False).all()
    reserves = Reserve.query.filter_by(is_active=True).all()

    last_recon = BankReconciliation.query.filter_by(
        financial_year_id=fy.id, is_complete=True
    ).order_by(BankReconciliation.year.desc(), BankReconciliation.month.desc()).first()
    bank_balance = Decimal(str(last_recon.closing_balance)) if last_recon else Decimal('0')

    # I&E surplus
    rows = _build_budget_rows(fy)
    income = sum(r['total'] for r in rows if r['heading'].is_income)
    expenditure = sum(r['total'] for r in rows if not r['heading'].is_income)
    ai = sum(Decimal(str(a.amount)) for a in accruals if a.accrual_type in ('accrued_income', 'debtor'))
    pp = sum(Decimal(str(a.amount)) for a in accruals if a.accrual_type == 'prepayment')
    ae = sum(Decimal(str(a.amount)) for a in accruals if a.accrual_type in ('accrued_expenditure', 'creditor'))
    surplus = (income + ai - pp) - (expenditure + ae)

    asset_accruals = [a for a in accruals if a.is_asset]
    liability_accruals = [a for a in accruals if not a.is_asset]

    total_fixed_assets = sum(a.net_book_value(fy.end_date) for a in assets)
    total_current_assets = bank_balance + sum(Decimal(str(a.amount)) for a in asset_accruals)
    total_liabilities = sum(Decimal(str(a.amount)) for a in liability_accruals)
    net_assets = total_fixed_assets + total_current_assets - total_liabilities

    total_reserves = sum(r.balance for r in reserves)

    return render_template('reports/balance_sheet.html',
                           fy=fy, settings=settings, assets=assets,
                           asset_accruals=asset_accruals,
                           liability_accruals=liability_accruals,
                           reserves=reserves,
                           bank_balance=bank_balance,
                           total_fixed_assets=total_fixed_assets,
                           total_current_assets=total_current_assets,
                           total_liabilities=total_liabilities,
                           net_assets=net_assets,
                           surplus=surplus,
                           total_reserves=total_reserves,
                           generated=datetime.now())
