"""
Reports & exports — PDF and CSV for cashbook, reconciliation, budget, VAT.
"""
import csv
import io
from decimal import Decimal
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required
from .models import FinancialYear, Transaction, BudgetHeading, Budget, BankReconciliation

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/')
@login_required
def index():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    return render_template('reports/index.html', fy=fy)


@reports_bp.route('/cashbook.csv')
@login_required
def cashbook_csv():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    txns = Transaction.query.filter_by(
        financial_year_id=fy.id
    ).order_by(Transaction.date, Transaction.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date', 'Reference', 'Type', 'Payee/Payer', 'Description',
        'Budget Heading', 'Net Amount (£)', 'VAT Amount (£)',
        'Gross Amount (£)', 'VAT Reclaimable', 'Notes', 'Void',
    ])
    for t in txns:
        writer.writerow([
            t.date.strftime('%d/%m/%Y'),
            t.reference,
            t.type_label,
            t.payee_payer,
            t.description,
            t.heading.name,
            f'{t.net_amount:.2f}',
            f'{t.vat_amount:.2f}',
            f'{t.gross_amount:.2f}',
            'Yes' if t.vat_reclaimable else 'No',
            t.notes or '',
            'Yes' if t.is_void else 'No',
        ])

    output.seek(0)
    filename = f'cashbook_{fy.label.replace("/", "-")}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@reports_bp.route('/budget.csv')
@login_required
def budget_csv():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Category', 'Heading', 'Budget (£)', 'Spent (£)', 'Remaining (£)', 'Notes'])
    for h in headings:
        bobj = Budget.query.filter_by(financial_year_id=fy.id, budget_heading_id=h.id).first()
        budget_amt = Decimal(str(bobj.effective_amount)) if bobj else Decimal('0')
        spent = sum(
            Decimal(str(t.net_amount))
            for t in Transaction.query.filter_by(
                financial_year_id=fy.id, budget_heading_id=h.id, is_void=False
            ).all()
        )
        note = ''
        if bobj and bobj.adjusted_amount is not None:
            note = f'Adjusted: {bobj.adjustment_note}'
        writer.writerow([
            h.category_label,
            h.name,
            f'{budget_amt:.2f}',
            f'{spent:.2f}',
            f'{budget_amt - spent:.2f}',
            note,
        ])

    output.seek(0)
    filename = f'budget_{fy.label.replace("/", "-")}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@reports_bp.route('/vat.csv')
@login_required
def vat_csv():
    fy = FinancialYear.query.filter_by(is_current=True).first()
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
    writer.writerow(['Date', 'Reference', 'Type', 'Payee/Payer', 'Description',
                     'Net (£)', 'VAT (£)', 'Reclaimable'])
    for t in vat_txns:
        writer.writerow([
            t.date.strftime('%d/%m/%Y'),
            t.reference,
            t.type_label,
            t.payee_payer,
            t.description,
            f'{t.net_amount:.2f}',
            f'{t.vat_amount:.2f}',
            'Yes' if t.vat_reclaimable else 'No',
        ])

    output.seek(0)
    filename = f'vat126_{fy.label.replace("/", "-")}_{datetime.today().strftime("%Y%m%d")}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@reports_bp.route('/receipts-and-payments')
@login_required
def receipts_and_payments():
    """HTML report suitable for printing / presenting to council."""
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('reports.index'))

    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    rows = []
    total_receipts = Decimal('0')
    total_payments = Decimal('0')
    for h in headings:
        spent = sum(
            Decimal(str(t.net_amount)) + Decimal(str(t.vat_amount))
            for t in Transaction.query.filter_by(
                financial_year_id=fy.id, budget_heading_id=h.id, is_void=False
            ).all()
        )
        rows.append({'heading': h, 'total': spent})
        if h.category == 'receipts':
            total_receipts += spent
        else:
            total_payments += spent

    return render_template('reports/receipts_and_payments.html',
                           fy=fy, rows=rows,
                           total_receipts=total_receipts,
                           total_payments=total_payments,
                           net=total_receipts - total_payments,
                           generated=datetime.now())
