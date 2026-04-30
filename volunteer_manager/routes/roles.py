from flask import Blueprint, request, jsonify, abort
from ..database import db
from ..models import Role, RoleSkillRequirement, Skill

bp = Blueprint("roles", __name__)


@bp.get("/")
def list_roles():
    org_id = request.args.get("org_id", type=int)
    q = Role.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    q = q.filter_by(active=True)
    return jsonify([r.to_dict() for r in q.order_by(Role.name).all()])


@bp.post("/")
def create_role():
    data = request.get_json(force=True)
    if not data.get("organisation_id") or not data.get("name"):
        abort(400, description="organisation_id and name are required")

    role = Role(
        organisation_id=data["organisation_id"],
        name=data["name"].strip(),
        description=data.get("description"),
        capacity=data.get("capacity"),
        requires_dbs=data.get("requires_dbs", False),
        dbs_level=data.get("dbs_level"),
    )
    db.session.add(role)
    db.session.flush()

    for sr in data.get("skill_requirements", []):
        db.session.add(RoleSkillRequirement(
            role_id=role.id,
            skill_id=sr["skill_id"],
            required=sr.get("required", True),
        ))

    db.session.commit()
    return jsonify(role.to_dict()), 201


@bp.get("/<int:role_id>")
def get_role(role_id):
    role = Role.query.get_or_404(role_id)
    return jsonify(role.to_dict())


@bp.patch("/<int:role_id>")
def update_role(role_id):
    role = Role.query.get_or_404(role_id)
    data = request.get_json(force=True)
    for field in ("name", "description", "capacity", "requires_dbs", "dbs_level", "active"):
        if field in data:
            setattr(role, field, data[field])
    db.session.commit()
    return jsonify(role.to_dict())


@bp.delete("/<int:role_id>")
def deactivate_role(role_id):
    role = Role.query.get_or_404(role_id)
    role.active = False
    db.session.commit()
    return jsonify({"deactivated": role_id})


# --- Skills catalogue ---

@bp.get("/skills/")
def list_skills():
    skills = Skill.query.order_by(Skill.category, Skill.name).all()
    return jsonify([s.to_dict() for s in skills])


@bp.post("/skills/")
def create_skill():
    data = request.get_json(force=True)
    if not data.get("name"):
        abort(400, description="name is required")
    skill = Skill(name=data["name"].strip(), category=data.get("category"))
    db.session.add(skill)
    db.session.commit()
    return jsonify(skill.to_dict()), 201
