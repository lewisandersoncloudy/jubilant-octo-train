"""Financial year management — create new years, switch current year."""
from datetime import date, datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, FinancialYear, log_action

financial_years_bp = Blueprint('financial_years', __name__, url_prefix='/financial-years')


@financial_years_bp.route('/')
@login_required
def index():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    years = FinancialYear.query.order_by(FinancialYear.start_date.desc()).all()
    return render_template('financial_years/index.html', years=years)


@financial_years_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        start_str = request.form.get('start_date', '').strip()
        end_str = request.form.get('end_date', '').strip()
        label = request.form.get('label', '').strip()
        make_current = request.form.get('make_current') == '1'

        errors = []
        try:
            start = date.fromisoformat(start_str)
        except (ValueError, AttributeError):
            errors.append('Invalid start date.')
            start = None
        try:
            end = date.fromisoformat(end_str)
        except (ValueError, AttributeError):
            errors.append('Invalid end date.')
            end = None

        if start and end and end <= start:
            errors.append('End date must be after start date.')
        if not label:
            errors.append('Label is required (e.g. 2026/27).')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('financial_years/new.html', form=request.form)

        if make_current:
            FinancialYear.query.update({'is_current': False})

        fy = FinancialYear(
            label=label,
            start_date=start,
            end_date=end,
            is_current=make_current,
        )
        db.session.add(fy)
        db.session.flush()
        log_action(current_user.id, 'financial_year', 'create',
                   f'Created financial year {label}', entity_id=fy.id)
        db.session.commit()
        flash(f'Financial year {label} created.', 'success')
        return redirect(url_for('financial_years.index'))

    # Default: next UK council year
    today = date.today()
    next_start = date(today.year if today.month < 4 else today.year + 1, 4, 1)
    next_end = date(next_start.year + 1, 3, 31)
    start_yr = next_start.year % 100
    end_yr = next_end.year % 100
    default_label = f'{next_start.year}/{end_yr:02d}'
    return render_template('financial_years/new.html',
                           form={'start_date': next_start, 'end_date': next_end,
                                 'label': default_label})


@financial_years_bp.route('/<int:fy_id>/set-current', methods=['POST'])
@login_required
def set_current(fy_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('financial_years.index'))

    FinancialYear.query.update({'is_current': False})
    fy = db.get_or_404(FinancialYear, fy_id)
    fy.is_current = True
    log_action(current_user.id, 'financial_year', 'set_current',
               f'Set {fy.label} as current financial year', entity_id=fy.id)
    db.session.commit()
    flash(f'{fy.label} is now the current financial year.', 'success')
    return redirect(url_for('financial_years.index'))
