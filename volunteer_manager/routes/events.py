from flask import Blueprint, request, jsonify, abort
from datetime import datetime, date
from ..database import db
from ..models import (
    Event, EventRole, EventAssignment, AttendanceRecord, VolunteerHours, Volunteer
)

bp = Blueprint("events", __name__)


@bp.get("/")
def list_events():
    org_id = request.args.get("org_id", type=int)
    status = request.args.get("status")
    upcoming = request.args.get("upcoming", type=int)  # 1 = only future events

    q = Event.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    if status:
        q = q.filter_by(status=status)
    if upcoming:
        q = q.filter(Event.start_datetime >= datetime.utcnow())

    events = q.order_by(Event.start_datetime).all()
    return jsonify([e.to_dict() for e in events])


@bp.post("/")
def create_event():
    data = request.get_json(force=True)
    required = ("organisation_id", "name", "start_datetime")
    missing = [f for f in required if not data.get(f)]
    if missing:
        abort(400, description=f"Missing: {', '.join(missing)}")

    event = Event(
        organisation_id=data["organisation_id"],
        name=data["name"].strip(),
        description=data.get("description"),
        location=data.get("location"),
        start_datetime=datetime.fromisoformat(data["start_datetime"]),
        end_datetime=datetime.fromisoformat(data["end_datetime"]) if data.get("end_datetime") else None,
        event_type=data.get("event_type", "one_off"),
        status=data.get("status", "planned"),
    )
    db.session.add(event)
    db.session.flush()

    for role_slot in data.get("roles", []):
        db.session.add(EventRole(
            event_id=event.id,
            role_id=role_slot["role_id"],
            slots_required=role_slot.get("slots_required", 1),
        ))

    db.session.commit()
    return jsonify(event.to_dict()), 201


@bp.get("/<int:event_id>")
def get_event(event_id):
    return jsonify(Event.query.get_or_404(event_id).to_dict())


@bp.patch("/<int:event_id>")
def update_event(event_id):
    event = Event.query.get_or_404(event_id)
    data = request.get_json(force=True)
    for field in ("name", "description", "location", "event_type", "status"):
        if field in data:
            setattr(event, field, data[field])
    for dt_field in ("start_datetime", "end_datetime"):
        if data.get(dt_field):
            setattr(event, dt_field, datetime.fromisoformat(data[dt_field]))
    db.session.commit()
    return jsonify(event.to_dict())


# --- Assignments ---

@bp.get("/<int:event_id>/assignments")
def list_assignments(event_id):
    event = Event.query.get_or_404(event_id)
    return jsonify([a.to_dict() for a in event.assignments])


@bp.post("/<int:event_id>/assignments")
def assign_volunteer(event_id):
    event = Event.query.get_or_404(event_id)
    data = request.get_json(force=True)

    if not data.get("volunteer_id") or not data.get("event_role_id"):
        abort(400, description="volunteer_id and event_role_id are required")

    # Clash check: same volunteer already assigned to overlapping event
    volunteer_id = data["volunteer_id"]
    clash = (
        EventAssignment.query
        .join(Event, EventAssignment.event_id == Event.id)
        .filter(
            EventAssignment.volunteer_id == volunteer_id,
            EventAssignment.status.in_(["assigned", "confirmed"]),
            Event.start_datetime < (event.end_datetime or event.start_datetime),
            Event.end_datetime > event.start_datetime if event.end_datetime else True,
            Event.id != event_id,
        )
        .first()
    )
    if clash:
        return jsonify({
            "error": "clash",
            "message": "Volunteer is already assigned to an overlapping event.",
            "conflicting_event_id": clash.event_id,
        }), 409

    # Capacity check
    event_role = EventRole.query.get_or_404(data["event_role_id"])
    if event_role.slots_available == 0:
        return jsonify({"error": "full", "message": "No slots available for this role."}), 409

    assignment = EventAssignment(
        event_id=event_id,
        event_role_id=data["event_role_id"],
        volunteer_id=volunteer_id,
        status=data.get("status", "assigned"),
        notes=data.get("notes"),
    )
    db.session.add(assignment)
    db.session.commit()
    return jsonify(assignment.to_dict()), 201


@bp.patch("/<int:event_id>/assignments/<int:assignment_id>")
def update_assignment(event_id, assignment_id):
    assignment = EventAssignment.query.filter_by(
        id=assignment_id, event_id=event_id
    ).first_or_404()
    data = request.get_json(force=True)
    if "status" in data:
        assignment.status = data["status"]
    if "notes" in data:
        assignment.notes = data["notes"]
    db.session.commit()
    return jsonify(assignment.to_dict())


@bp.delete("/<int:event_id>/assignments/<int:assignment_id>")
def remove_assignment(event_id, assignment_id):
    assignment = EventAssignment.query.filter_by(
        id=assignment_id, event_id=event_id
    ).first_or_404()
    db.session.delete(assignment)
    db.session.commit()
    return jsonify({"deleted": assignment_id})


# --- Attendance ---

@bp.get("/<int:event_id>/attendance")
def get_attendance(event_id):
    Event.query.get_or_404(event_id)
    records = AttendanceRecord.query.filter_by(event_id=event_id).all()
    return jsonify([r.to_dict() for r in records])


@bp.post("/<int:event_id>/attendance")
def record_attendance(event_id):
    Event.query.get_or_404(event_id)
    data = request.get_json(force=True)
    records = data if isinstance(data, list) else [data]

    results = []
    for item in records:
        volunteer_id = item.get("volunteer_id")
        if not volunteer_id:
            continue
        existing = AttendanceRecord.query.filter_by(
            event_id=event_id, volunteer_id=volunteer_id
        ).first()
        if existing:
            existing.present = item.get("present", existing.present)
            if item.get("checked_in_at"):
                existing.checked_in_at = datetime.fromisoformat(item["checked_in_at"])
            if item.get("checked_out_at"):
                existing.checked_out_at = datetime.fromisoformat(item["checked_out_at"])
            results.append(existing)
        else:
            rec = AttendanceRecord(
                event_id=event_id,
                volunteer_id=volunteer_id,
                present=item.get("present", True),
                recorded_by=item.get("recorded_by"),
            )
            if item.get("checked_in_at"):
                rec.checked_in_at = datetime.fromisoformat(item["checked_in_at"])
            db.session.add(rec)
            results.append(rec)

    db.session.commit()
    return jsonify([r.to_dict() for r in results]), 201
