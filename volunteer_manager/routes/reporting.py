from flask import Blueprint, request, jsonify
from datetime import date, datetime, timedelta
from sqlalchemy import func
from ..database import db
from ..models import (
    Volunteer, Event, EventAssignment, AttendanceRecord, VolunteerHours,
    DBSCheck, TrainingRequirement, VolunteerTraining, Role
)

bp = Blueprint("reporting", __name__)

VOLUNTEER_HOUR_VALUE_GBP = 12.21  # National Living Wage – standard impact valuation


@bp.get("/summary")
def organisation_summary():
    """High-level dashboard numbers for an organisation."""
    org_id = request.args.get("org_id", type=int)
    if not org_id:
        return jsonify({"error": "org_id is required"}), 400

    volunteers = Volunteer.query.filter_by(organisation_id=org_id)
    active = volunteers.filter_by(status="active").count()
    on_hold = volunteers.filter_by(status="on_hold").count()
    left = volunteers.filter_by(status="left").count()

    total_hours = db.session.query(func.sum(VolunteerHours.hours)).join(
        Volunteer, VolunteerHours.volunteer_id == Volunteer.id
    ).filter(Volunteer.organisation_id == org_id).scalar() or 0

    today = date.today()
    events_this_month = Event.query.filter(
        Event.organisation_id == org_id,
        func.strftime("%Y-%m", Event.start_datetime) == today.strftime("%Y-%m"),
    ).count()

    upcoming_events = Event.query.filter(
        Event.organisation_id == org_id,
        Event.start_datetime >= datetime.utcnow(),
        Event.status.in_(["planned", "active"]),
    ).count()

    # Compliance alerts
    cutoff_90 = today + timedelta(days=90)
    dbs_expiring = DBSCheck.query.join(Volunteer).filter(
        Volunteer.organisation_id == org_id,
        DBSCheck.expiry_date.between(today, cutoff_90),
    ).count()
    training_expiring = VolunteerTraining.query.join(Volunteer).filter(
        Volunteer.organisation_id == org_id,
        VolunteerTraining.expiry_date.between(today, cutoff_90),
    ).count()

    return jsonify({
        "volunteers": {
            "active": active,
            "on_hold": on_hold,
            "left": left,
            "total": active + on_hold + left,
        },
        "hours": {
            "total": round(total_hours, 1),
            "estimated_value_gbp": round(total_hours * VOLUNTEER_HOUR_VALUE_GBP, 2),
        },
        "events": {
            "this_month": events_this_month,
            "upcoming": upcoming_events,
        },
        "compliance_alerts": {
            "dbs_expiring_90_days": dbs_expiring,
            "training_expiring_90_days": training_expiring,
        },
    })


@bp.get("/volunteers/activity")
def volunteer_activity():
    """Per-volunteer hours and attendance breakdown."""
    org_id = request.args.get("org_id", type=int)
    if not org_id:
        return jsonify({"error": "org_id is required"}), 400

    since = request.args.get("since")  # ISO date
    since_date = date.fromisoformat(since) if since else date(date.today().year, 1, 1)

    rows = (
        db.session.query(
            Volunteer.id,
            Volunteer.first_name,
            Volunteer.last_name,
            Volunteer.email,
            func.coalesce(func.sum(VolunteerHours.hours), 0).label("hours"),
            func.coalesce(func.sum(VolunteerHours.miles_travelled), 0).label("miles"),
        )
        .outerjoin(VolunteerHours, (VolunteerHours.volunteer_id == Volunteer.id) &
                   (VolunteerHours.date >= since_date))
        .filter(Volunteer.organisation_id == org_id, Volunteer.status == "active")
        .group_by(Volunteer.id)
        .order_by(func.sum(VolunteerHours.hours).desc().nullslast())
        .all()
    )

    return jsonify({
        "since": since_date.isoformat(),
        "volunteers": [
            {
                "id": r.id,
                "name": f"{r.first_name} {r.last_name}",
                "email": r.email,
                "hours": round(float(r.hours), 1),
                "miles": round(float(r.miles), 1),
                "estimated_value_gbp": round(float(r.hours) * VOLUNTEER_HOUR_VALUE_GBP, 2),
            }
            for r in rows
        ],
    })


@bp.get("/compliance/overview")
def compliance_overview():
    """Trustee-grade compliance summary – % volunteers with current DBS / training."""
    org_id = request.args.get("org_id", type=int)
    if not org_id:
        return jsonify({"error": "org_id is required"}), 400

    active_vols = Volunteer.query.filter_by(
        organisation_id=org_id, status="active"
    ).all()
    total = len(active_vols)
    if total == 0:
        return jsonify({"total_active_volunteers": 0})

    today = date.today()
    with_valid_dbs = sum(
        1 for v in active_vols
        if any(
            c for c in v.dbs_checks
            if not c.is_expired
        )
    )

    # Training: only count mandatory requirements
    mandatory_reqs = TrainingRequirement.query.filter_by(
        organisation_id=org_id, mandatory=True
    ).all()
    req_ids = {r.id for r in mandatory_reqs}

    fully_trained = 0
    if req_ids:
        for v in active_vols:
            completed_ids = {
                tr.requirement_id for tr in v.training_records
                if not tr.is_expired and tr.requirement_id in req_ids
            }
            if req_ids.issubset(completed_ids):
                fully_trained += 1
    else:
        fully_trained = total

    return jsonify({
        "total_active_volunteers": total,
        "dbs": {
            "with_valid_dbs": with_valid_dbs,
            "without_valid_dbs": total - with_valid_dbs,
            "percent": round(with_valid_dbs / total * 100, 1),
        },
        "training": {
            "mandatory_requirements": len(req_ids),
            "fully_trained": fully_trained,
            "not_fully_trained": total - fully_trained,
            "percent": round(fully_trained / total * 100, 1),
        },
    })


@bp.get("/events/summary")
def event_summary():
    """Events report: attendance rates, volunteer coverage."""
    org_id = request.args.get("org_id", type=int)
    if not org_id:
        return jsonify({"error": "org_id is required"}), 400

    since = request.args.get("since")
    since_dt = datetime.fromisoformat(since) if since else datetime(date.today().year, 1, 1)

    events = Event.query.filter(
        Event.organisation_id == org_id,
        Event.start_datetime >= since_dt,
        Event.status == "completed",
    ).all()

    result = []
    for e in events:
        attended = AttendanceRecord.query.filter_by(event_id=e.id, present=True).count()
        assigned = len(e.assignments)
        total_hours = sum(
            h.hours for h in VolunteerHours.query.filter_by(event_id=e.id).all()
        )
        result.append({
            "event_id": e.id,
            "name": e.name,
            "date": e.start_datetime.date().isoformat(),
            "volunteers_assigned": assigned,
            "volunteers_attended": attended,
            "attendance_rate": round(attended / assigned * 100, 1) if assigned else 0,
            "total_hours": round(total_hours, 1),
        })

    return jsonify(result)


@bp.get("/inactivity")
def inactive_volunteers():
    """Volunteers who haven't been assigned to any event in the last N days."""
    org_id = request.args.get("org_id", type=int)
    days = request.args.get("days", 90, type=int)
    if not org_id:
        return jsonify({"error": "org_id is required"}), 400

    cutoff = datetime.utcnow() - timedelta(days=days)
    active_vols = Volunteer.query.filter_by(
        organisation_id=org_id, status="active"
    ).all()

    inactive = []
    for v in active_vols:
        last = (
            EventAssignment.query
            .join(Event, EventAssignment.event_id == Event.id)
            .filter(EventAssignment.volunteer_id == v.id)
            .order_by(Event.start_datetime.desc())
            .first()
        )
        last_date = last.event.start_datetime if last else None
        if not last_date or last_date < cutoff:
            inactive.append({
                "volunteer": v.to_dict(),
                "last_assignment": last_date.isoformat() if last_date else None,
                "days_inactive": (
                    (datetime.utcnow() - last_date).days if last_date else None
                ),
            })

    return jsonify(inactive)
