from flask import Blueprint, flash, redirect, render_template, request, url_for

from bridge_crm.crm.auth.queries import (
    VALID_USER_ROLES,
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
from bridge_crm.crm.auth.routes import admin_required

users_bp = Blueprint("users", __name__, url_prefix="/users")


def _normalize_role(value: str | None) -> str:
    role = (value or "rep").strip().lower()
    return role if role in VALID_USER_ROLES else "rep"


@users_bp.route("/")
@admin_required
def list_view():
    users = list_users()
    return render_template("users/list.html", users=users)


@users_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create_view():
    form_data = request.form if request.method == "POST" else {}

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        role = _normalize_role(request.form.get("role"))
        password = request.form.get("password", "")
        is_active = request.form.get("is_active") == "on"

        if not email or not full_name or not password:
            flash("Email, full name, and password are required.", "danger")
        elif len(password) < 12:
            flash("Password must be at least 12 characters.", "danger")
        elif get_user_by_email(email):
            flash("A user with that email already exists.", "danger")
        else:
            create_user(
                email=email,
                password=password,
                full_name=full_name,
                role=role,
                is_active=is_active,
            )
            flash("User created.", "success")
            return redirect(url_for("users.list_view"))

    return render_template(
        "users/form.html",
        user_record=None,
        form_data=form_data,
        page_title="New User",
        submit_label="Create User",
        role_options=VALID_USER_ROLES,
    )


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_view(user_id: int):
    user_record = get_user_by_id(user_id)
    if not user_record:
        flash("User not found.", "danger")
        return redirect(url_for("users.list_view"))

    form_data = request.form if request.method == "POST" else user_record
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = _normalize_role(request.form.get("role"))
        password = request.form.get("password", "")
        is_active = request.form.get("is_active") == "on"

        if not full_name:
            flash("Full name is required.", "danger")
        elif password and len(password) < 12:
            flash("Password must be at least 12 characters.", "danger")
        else:
            update_user(
                user_id=user_id,
                full_name=full_name,
                role=role,
                is_active=is_active,
                password=password or None,
            )
            flash("User updated.", "success")
            return redirect(url_for("users.list_view"))

    return render_template(
        "users/form.html",
        user_record=user_record,
        form_data=form_data,
        page_title="Edit User",
        submit_label="Save User",
        role_options=VALID_USER_ROLES,
    )
