from flask import Blueprint, request, jsonify
from datetime import datetime
from ..database import db
from ..models import Volunteer, AvailabilitySlot, EventAssignment, Event, Role

bp = Blueprint("scheduling", __name__)


@bp.get("/available")
def find_available_volunteers():
    """
    Return volunteers available for a given date/time and optionally a role.
    Query params:
      - org_id (required)
      - start_datetime (ISO, required)
      - end_datetime   (ISO, optional)
      - role_id        (optional) – filter by volunteers whose skills match
    """
    org_id = request.args.get("org_id", type=int)
    start_str = request.args.get("start_datetime")
    end_str = request.args.get("end_datetime")
    role_id = request.args.get("role_id", type=int)

    if not org_id or not start_str:
        return jsonify({"error": "org_id and start_datetime are required"}), 400

    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str) if end_str else start_dt
    day_of_week = start_dt.weekday()

    # Start with active volunteers in the org
    volunteers = Volunteer.query.filter_by(
        organisation_id=org_id, status="active"
    ).all()

    # Filter by role skill requirements
    if role_id:
        role = Role.query.get(role_id)
        if role:
            required_skill_ids = {
                sr.skill_id for sr in role.skill_requirements if sr.required
            }
            if required_skill_ids:
                volunteers = [
                    v for v in volunteers
                    if required_skill_ids.issubset({vs.skill_id for vs in v.skills})
                ]

    # Filter out volunteers already assigned to overlapping events
    conflicted_ids = set()
    for v in volunteers:
        clash = (
            EventAssignment.query
            .join(Event, EventAssignment.event_id == Event.id)
            .filter(
                EventAssignment.volunteer_id == v.id,
                EventAssignment.status.in_(["assigned", "confirmed"]),
                Event.start_datetime < end_dt,
                db.or_(Event.end_datetime > start_dt, Event.end_datetime.is_(None)),
            )
            .first()
        )
        if clash:
            conflicted_ids.add(v.id)

    # Check recurring availability slots
    available = []
    unavailable = []
    for v in volunteers:
        if v.id in conflicted_ids:
            unavailable.append({"volunteer": v.to_dict(), "reason": "scheduling_clash"})
            continue

        slots = AvailabilitySlot.query.filter_by(
            volunteer_id=v.id, slot_type="recurring", day_of_week=day_of_week
        ).all()

        explicit_unavailable = AvailabilitySlot.query.filter_by(
            volunteer_id=v.id,
            slot_type="unavailable",
            date=start_dt.date(),
        ).first()

        if explicit_unavailable:
            unavailable.append({"volunteer": v.to_dict(), "reason": "marked_unavailable"})
            continue

        if not slots:
            # No recurring slot set for this day — include as potentially available
            available.append({"volunteer": v.to_dict(), "availability": "unspecified"})
        else:
            # Check if any slot covers the requested time
            covers = any(
                (s.start_time is None or s.start_time <= start_dt.time()) and
                (s.end_time is None or s.end_time >= end_dt.time())
                for s in slots
            )
            if covers:
                available.append({"volunteer": v.to_dict(), "availability": "confirmed"})
            else:
                available.append({"volunteer": v.to_dict(), "availability": "partial"})

    return jsonify({
        "available": available,
        "unavailable": unavailable,
        "total_available": len(available),
    })


@bp.get("/calendar")
def calendar_view():
    """Return events and assignments for a date range (for a rota/calendar view)."""
    org_id = request.args.get("org_id", type=int)
    start_str = request.args.get("start")
    end_str = request.args.get("end")

    if not org_id or not start_str or not end_str:
        return jsonify({"error": "org_id, start and end are required"}), 400

    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str)

    events = Event.query.filter(
        Event.organisation_id == org_id,
        Event.start_datetime >= start_dt,
        Event.start_datetime <= end_dt,
    ).order_by(Event.start_datetime).all()

    return jsonify([
        {
            **e.to_dict(),
            "assignments": [a.to_dict() for a in e.assignments],
        }
        for e in events
    ])


@bp.get("/gaps")
def coverage_gaps():
    """Return event roles with unfilled slots."""
    org_id = request.args.get("org_id", type=int)
    from ..models import EventRole

    q = EventRole.query.join(Event).filter(
        Event.status.in_(["planned", "active"]),
    )
    if org_id:
        q = q.filter(Event.organisation_id == org_id)

    gaps = []
    for er in q.all():
        if er.slots_available and er.slots_available > 0:
            gaps.append({
                "event_id": er.event_id,
                "event_name": er.event.name,
                "event_start": er.event.start_datetime.isoformat(),
                "role": er.role.to_dict() if er.role else None,
                "slots_required": er.slots_required,
                "slots_filled": er.slots_filled,
                "slots_available": er.slots_available,
            })

    return jsonify(gaps)
