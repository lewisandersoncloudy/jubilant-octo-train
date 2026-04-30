from flask import Blueprint, request, jsonify, abort
from datetime import date, datetime, timedelta
from ..database import db
from ..models import (
    DBSCheck, TrainingRequirement, VolunteerTraining,
    SafeguardingConcern, ConsentRecord, Volunteer
)

bp = Blueprint("compliance", __name__)


# ── DBS Checks ──────────────────────────────────────────────────────────────

@bp.get("/dbs/<int:volunteer_id>")
def list_dbs(volunteer_id):
    Volunteer.query.get_or_404(volunteer_id)
    checks = DBSCheck.query.filter_by(volunteer_id=volunteer_id).order_by(DBSCheck.issue_date.desc()).all()
    return jsonify([c.to_dict() for c in checks])


@bp.post("/dbs/<int:volunteer_id>")
def add_dbs(volunteer_id):
    Volunteer.query.get_or_404(volunteer_id)
    data = request.get_json(force=True)
    if not data.get("check_type") or not data.get("issue_date"):
        abort(400, description="check_type and issue_date are required")

    check = DBSCheck(
        volunteer_id=volunteer_id,
        check_type=data["check_type"],
        reference_number=data.get("reference_number"),
        issue_date=date.fromisoformat(data["issue_date"]),
        expiry_date=date.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
        verified_by=data.get("verified_by"),
        verified_at=datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else None,
        notes=data.get("notes"),
    )
    db.session.add(check)
    db.session.commit()
    return jsonify(check.to_dict()), 201


@bp.patch("/dbs/<int:check_id>")
def update_dbs(check_id):
    check = DBSCheck.query.get_or_404(check_id)
    data = request.get_json(force=True)
    for field in ("check_type", "reference_number", "notes"):
        if field in data:
            setattr(check, field, data[field])
    for date_field in ("issue_date", "expiry_date"):
        if data.get(date_field):
            setattr(check, date_field, date.fromisoformat(data[date_field]))
    if data.get("verified_by"):
        check.verified_by = data["verified_by"]
        check.verified_at = datetime.utcnow()
    db.session.commit()
    return jsonify(check.to_dict())


# ── Training ─────────────────────────────────────────────────────────────────

@bp.get("/training/requirements")
def list_training_requirements():
    org_id = request.args.get("org_id", type=int)
    q = TrainingRequirement.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    return jsonify([r.to_dict() for r in q.all()])


@bp.post("/training/requirements")
def create_training_requirement():
    data = request.get_json(force=True)
    if not data.get("organisation_id") or not data.get("name"):
        abort(400, description="organisation_id and name are required")
    req = TrainingRequirement(
        organisation_id=data["organisation_id"],
        name=data["name"].strip(),
        description=data.get("description"),
        validity_months=data.get("validity_months"),
        mandatory=data.get("mandatory", True),
        applies_to_role_id=data.get("applies_to_role_id"),
    )
    db.session.add(req)
    db.session.commit()
    return jsonify(req.to_dict()), 201


@bp.get("/training/<int:volunteer_id>")
def list_volunteer_training(volunteer_id):
    Volunteer.query.get_or_404(volunteer_id)
    records = VolunteerTraining.query.filter_by(volunteer_id=volunteer_id).all()
    return jsonify([r.to_dict() for r in records])


@bp.post("/training/<int:volunteer_id>")
def record_training(volunteer_id):
    Volunteer.query.get_or_404(volunteer_id)
    data = request.get_json(force=True)
    if not data.get("requirement_id") or not data.get("completed_date"):
        abort(400, description="requirement_id and completed_date are required")

    req = TrainingRequirement.query.get_or_404(data["requirement_id"])

    completed = date.fromisoformat(data["completed_date"])
    expiry = None
    if req.validity_months:
        from dateutil.relativedelta import relativedelta
        expiry = completed + relativedelta(months=req.validity_months)
    if data.get("expiry_date"):
        expiry = date.fromisoformat(data["expiry_date"])

    record = VolunteerTraining(
        volunteer_id=volunteer_id,
        requirement_id=req.id,
        completed_date=completed,
        expiry_date=expiry,
        notes=data.get("notes"),
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(record.to_dict()), 201


# ── Expiry dashboard ─────────────────────────────────────────────────────────

@bp.get("/expiring")
def expiring_items():
    """Return DBS and training records expiring within the next N days."""
    org_id = request.args.get("org_id", type=int)
    days = request.args.get("days", 90, type=int)
    cutoff = date.today() + timedelta(days=days)

    dbs_q = DBSCheck.query.filter(
        DBSCheck.expiry_date <= cutoff,
        DBSCheck.expiry_date >= date.today(),
    )
    training_q = VolunteerTraining.query.filter(
        VolunteerTraining.expiry_date <= cutoff,
        VolunteerTraining.expiry_date >= date.today(),
    )

    if org_id:
        dbs_q = dbs_q.join(Volunteer).filter(Volunteer.organisation_id == org_id)
        training_q = training_q.join(Volunteer).filter(Volunteer.organisation_id == org_id)

    return jsonify({
        "dbs": [c.to_dict() | {"volunteer_name": c.volunteer.full_name} for c in dbs_q.all()],
        "training": [
            r.to_dict() | {"volunteer_name": r.volunteer.full_name}
            for r in training_q.all()
        ],
    })


@bp.get("/overdue")
def overdue_items():
    """Return DBS and training records that have already expired."""
    org_id = request.args.get("org_id", type=int)

    dbs_q = DBSCheck.query.filter(DBSCheck.expiry_date < date.today())
    training_q = VolunteerTraining.query.filter(VolunteerTraining.expiry_date < date.today())

    if org_id:
        dbs_q = dbs_q.join(Volunteer).filter(Volunteer.organisation_id == org_id)
        training_q = training_q.join(Volunteer).filter(Volunteer.organisation_id == org_id)

    return jsonify({
        "dbs": [c.to_dict() | {"volunteer_name": c.volunteer.full_name} for c in dbs_q.all()],
        "training": [
            r.to_dict() | {"volunteer_name": r.volunteer.full_name}
            for r in training_q.all()
        ],
    })


# ── Safeguarding ─────────────────────────────────────────────────────────────

@bp.get("/safeguarding")
def list_concerns():
    org_id = request.args.get("org_id", type=int)
    q = SafeguardingConcern.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    concerns = q.order_by(SafeguardingConcern.reported_at.desc()).all()
    return jsonify([c.to_dict() for c in concerns])


@bp.post("/safeguarding")
def create_concern():
    data = request.get_json(force=True)
    required = ("organisation_id", "reported_by", "description")
    missing = [f for f in required if not data.get(f)]
    if missing:
        abort(400, description=f"Missing: {', '.join(missing)}")

    concern = SafeguardingConcern(
        organisation_id=data["organisation_id"],
        volunteer_id=data.get("volunteer_id"),
        reported_by=data["reported_by"],
        description=data["description"],
        category=data.get("category"),
        severity=data.get("severity", "low"),
    )
    db.session.add(concern)
    db.session.commit()
    return jsonify(concern.to_dict()), 201


@bp.patch("/safeguarding/<int:concern_id>")
def update_concern(concern_id):
    concern = SafeguardingConcern.query.get_or_404(concern_id)
    data = request.get_json(force=True)
    for field in ("status", "escalated_to", "resolution_notes", "severity"):
        if field in data:
            setattr(concern, field, data[field])
    if data.get("status") == "closed" and not concern.resolved_at:
        concern.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify(concern.to_dict())


# ── Consent ──────────────────────────────────────────────────────────────────

@bp.get("/consent/<int:volunteer_id>")
def list_consent(volunteer_id):
    Volunteer.query.get_or_404(volunteer_id)
    records = ConsentRecord.query.filter_by(volunteer_id=volunteer_id).all()
    return jsonify([r.to_dict() for r in records])


@bp.post("/consent/<int:volunteer_id>")
def record_consent(volunteer_id):
    Volunteer.query.get_or_404(volunteer_id)
    data = request.get_json(force=True)
    if not data.get("consent_type"):
        abort(400, description="consent_type is required")

    record = ConsentRecord(
        volunteer_id=volunteer_id,
        consent_type=data["consent_type"],
        version=data.get("version", "1.0"),
        granted=data.get("granted", True),
        granted_at=datetime.utcnow() if data.get("granted") else None,
        withdrawn_at=datetime.utcnow() if not data.get("granted") else None,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(record.to_dict()), 201
