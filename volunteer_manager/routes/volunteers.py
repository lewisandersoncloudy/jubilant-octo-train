from flask import Blueprint, request, jsonify, abort
from datetime import date
from ..database import db
from ..models import (
    Volunteer, EmergencyContact, VolunteerSkill, AvailabilitySlot, Skill
)

bp = Blueprint("volunteers", __name__)


def _get_volunteer_or_404(volunteer_id):
    v = Volunteer.query.get(volunteer_id)
    if not v:
        abort(404, description="Volunteer not found")
    return v


@bp.get("/")
def list_volunteers():
    org_id = request.args.get("org_id", type=int)
    status = request.args.get("status")
    search = request.args.get("q", "").strip()

    q = Volunteer.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    if status:
        q = q.filter_by(status=status)
    if search:
        like = f"%{search}%"
        q = q.filter(
            db.or_(
                Volunteer.first_name.ilike(like),
                Volunteer.last_name.ilike(like),
                Volunteer.email.ilike(like),
            )
        )

    volunteers = q.order_by(Volunteer.last_name, Volunteer.first_name).all()
    return jsonify([v.to_dict() for v in volunteers])


@bp.post("/")
def create_volunteer():
    data = request.get_json(force=True)
    required = ("organisation_id", "first_name", "last_name", "email")
    missing = [f for f in required if not data.get(f)]
    if missing:
        abort(400, description=f"Missing required fields: {', '.join(missing)}")

    volunteer = Volunteer(
        organisation_id=data["organisation_id"],
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        email=data["email"].strip().lower(),
        phone=data.get("phone"),
        address=data.get("address"),
        notes=data.get("notes"),
        interests=data.get("interests"),
        preferred_contact=data.get("preferred_contact", "email"),
        status=data.get("status", "active"),
    )
    if data.get("date_of_birth"):
        volunteer.date_of_birth = date.fromisoformat(data["date_of_birth"])
    if data.get("joined_date"):
        volunteer.joined_date = date.fromisoformat(data["joined_date"])

    db.session.add(volunteer)
    db.session.flush()

    # Emergency contact
    ec = data.get("emergency_contact")
    if ec and ec.get("name"):
        db.session.add(EmergencyContact(
            volunteer_id=volunteer.id,
            name=ec["name"],
            relationship=ec.get("relationship"),
            phone=ec.get("phone", ""),
            email=ec.get("email"),
        ))

    db.session.commit()
    return jsonify(volunteer.to_dict(include_sensitive=True)), 201


@bp.get("/<int:volunteer_id>")
def get_volunteer(volunteer_id):
    v = _get_volunteer_or_404(volunteer_id)
    return jsonify(v.to_dict(include_sensitive=True))


@bp.patch("/<int:volunteer_id>")
def update_volunteer(volunteer_id):
    v = _get_volunteer_or_404(volunteer_id)
    data = request.get_json(force=True)

    for field in ("first_name", "last_name", "email", "phone", "address",
                  "notes", "interests", "preferred_contact", "status"):
        if field in data:
            setattr(v, field, data[field])

    for date_field in ("date_of_birth", "joined_date", "left_date"):
        if date_field in data and data[date_field]:
            setattr(v, date_field, date.fromisoformat(data[date_field]))

    db.session.commit()
    return jsonify(v.to_dict(include_sensitive=True))


@bp.delete("/<int:volunteer_id>")
def delete_volunteer(volunteer_id):
    v = _get_volunteer_or_404(volunteer_id)
    db.session.delete(v)
    db.session.commit()
    return jsonify({"deleted": volunteer_id})


# --- Skills ---

@bp.post("/<int:volunteer_id>/skills")
def add_skill(volunteer_id):
    v = _get_volunteer_or_404(volunteer_id)
    data = request.get_json(force=True)
    skill_id = data.get("skill_id")
    if not skill_id:
        abort(400, description="skill_id required")

    existing = VolunteerSkill.query.filter_by(
        volunteer_id=volunteer_id, skill_id=skill_id
    ).first()
    if not existing:
        db.session.add(VolunteerSkill(
            volunteer_id=volunteer_id,
            skill_id=skill_id,
            level=data.get("level", "competent"),
        ))
        db.session.commit()
    return jsonify(v.to_dict()), 201


@bp.delete("/<int:volunteer_id>/skills/<int:skill_id>")
def remove_skill(volunteer_id, skill_id):
    vs = VolunteerSkill.query.filter_by(
        volunteer_id=volunteer_id, skill_id=skill_id
    ).first_or_404()
    db.session.delete(vs)
    db.session.commit()
    return jsonify({"removed": skill_id})


# --- Availability ---

@bp.get("/<int:volunteer_id>/availability")
def get_availability(volunteer_id):
    _get_volunteer_or_404(volunteer_id)
    slots = AvailabilitySlot.query.filter_by(volunteer_id=volunteer_id).all()
    return jsonify([s.to_dict() for s in slots])


@bp.post("/<int:volunteer_id>/availability")
def add_availability(volunteer_id):
    _get_volunteer_or_404(volunteer_id)
    data = request.get_json(force=True)

    from datetime import time
    slot = AvailabilitySlot(
        volunteer_id=volunteer_id,
        day_of_week=data.get("day_of_week"),
        slot_type=data.get("slot_type", "recurring"),
    )
    if data.get("start_time"):
        h, m = map(int, data["start_time"].split(":"))
        slot.start_time = time(h, m)
    if data.get("end_time"):
        h, m = map(int, data["end_time"].split(":"))
        slot.end_time = time(h, m)
    if data.get("date"):
        slot.date = date.fromisoformat(data["date"])

    db.session.add(slot)
    db.session.commit()
    return jsonify(slot.to_dict()), 201


@bp.delete("/<int:volunteer_id>/availability/<int:slot_id>")
def delete_availability(volunteer_id, slot_id):
    slot = AvailabilitySlot.query.filter_by(
        id=slot_id, volunteer_id=volunteer_id
    ).first_or_404()
    db.session.delete(slot)
    db.session.commit()
    return jsonify({"deleted": slot_id})


# --- Hours log ---

@bp.get("/<int:volunteer_id>/hours")
def get_hours(volunteer_id):
    from ..models import VolunteerHours
    v = _get_volunteer_or_404(volunteer_id)
    logs = (
        VolunteerHours.query
        .filter_by(volunteer_id=volunteer_id)
        .order_by(VolunteerHours.date.desc())
        .all()
    )
    return jsonify({
        "total_hours": v.total_hours,
        "logs": [h.to_dict() for h in logs],
    })


@bp.post("/<int:volunteer_id>/hours")
def log_hours(volunteer_id):
    from ..models import VolunteerHours
    _get_volunteer_or_404(volunteer_id)
    data = request.get_json(force=True)
    if not data.get("hours") or not data.get("date"):
        abort(400, description="hours and date are required")

    entry = VolunteerHours(
        volunteer_id=volunteer_id,
        date=date.fromisoformat(data["date"]),
        hours=float(data["hours"]),
        miles_travelled=float(data.get("miles_travelled", 0)),
        description=data.get("description"),
        event_id=data.get("event_id"),
        logged_by=data.get("logged_by"),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201
