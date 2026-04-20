from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from bridge_crm.crm.auth.routes import admin_required
from bridge_crm.crm.custom_fields.queries import (
    VALID_FIELD_TYPES,
    VALID_OBJECT_TYPES,
    build_custom_field_payload,
    create_custom_field,
    get_custom_field,
    get_custom_field_by_key,
    list_custom_fields,
    update_custom_field,
)

custom_fields_bp = Blueprint(
    "custom_fields",
    __name__,
    url_prefix="/setup/custom-fields",
    template_folder="../../templates",
)


@custom_fields_bp.route("/")
@admin_required
def list_view():
    object_type = request.args.get("object_type", "").strip().lower() or None
    fields = list_custom_fields(object_type=object_type)
    return render_template(
        "setup/custom_fields_list.html",
        fields=fields,
        object_type=object_type or "all",
        object_types=VALID_OBJECT_TYPES,
    )


@custom_fields_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create_view():
    form_data = request.form if request.method == "POST" else {"field_type": "text", "is_active": True}

    if request.method == "POST":
        payload = build_custom_field_payload(request.form, g.user["id"])
        if payload["object_type"] not in VALID_OBJECT_TYPES:
            flash("Choose a valid object type.", "danger")
        elif not payload["field_label"] or not payload["field_key"]:
            flash("Field label and key are required.", "danger")
        elif get_custom_field_by_key(payload["object_type"], payload["field_key"]):
            flash("That field key already exists for this object.", "danger")
        else:
            create_custom_field(payload)
            flash("Custom field created.", "success")
            return redirect(url_for("custom_fields.list_view", object_type=payload["object_type"]))

    return render_template(
        "setup/custom_field_form.html",
        field=None,
        form_data=form_data,
        page_title="New Custom Field",
        submit_label="Create Field",
        object_types=VALID_OBJECT_TYPES,
        field_types=VALID_FIELD_TYPES,
    )


@custom_fields_bp.route("/<int:field_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_view(field_id: int):
    field = get_custom_field(field_id)
    if not field:
        flash("Custom field not found.", "danger")
        return redirect(url_for("custom_fields.list_view"))

    form_data = request.form if request.method == "POST" else {
        **field,
        "options_raw": "\n".join(field.get("options_json") or []),
    }
    if request.method == "POST":
        payload = build_custom_field_payload(request.form, field["created_by"], existing=field)
        existing = get_custom_field_by_key(payload["object_type"], payload["field_key"])
        if payload["object_type"] not in VALID_OBJECT_TYPES:
            flash("Choose a valid object type.", "danger")
        elif not payload["field_label"] or not payload["field_key"]:
            flash("Field label and key are required.", "danger")
        elif existing and existing["id"] != field_id:
            flash("That field key already exists for this object.", "danger")
        else:
            update_custom_field(field_id, payload)
            flash("Custom field updated.", "success")
            return redirect(url_for("custom_fields.list_view", object_type=payload["object_type"]))

    return render_template(
        "setup/custom_field_form.html",
        field=field,
        form_data=form_data,
        page_title="Edit Custom Field",
        submit_label="Save Field",
        object_types=VALID_OBJECT_TYPES,
        field_types=VALID_FIELD_TYPES,
    )
