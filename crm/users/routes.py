from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from bridge_crm.crm.auth.queries import (
    VALID_USER_ROLES,
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
from bridge_crm.crm.auth.routes import admin_required, send_password_reset_email
from bridge_crm.integrations.email_sender import send_email, smtp_configured

users_bp = Blueprint(
    "users",
    __name__,
    url_prefix="/users",
    template_folder="../../templates",
)


def _normalize_role(value: str | None) -> str:
    role = (value or "rep").strip().lower()
    return role if role in VALID_USER_ROLES else "rep"


@users_bp.route("/")
@admin_required
def list_view():
    users = list_users()
    return render_template("users/list.html", users=users, email_ready=smtp_configured())


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
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
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
            if smtp_configured():
                try:
                    login_url = url_for("auth.login", _external=True)
                    send_email(
                        to_address=email,
                        subject="Your Bridge CRM account has been created",
                        body_text=(
                            f"Hi {full_name},\n\n"
                            f"An account has been created for you on Bridge CRM.\n\n"
                            f"Email: {email}\n"
                            f"Password: {password}\n"
                            f"Role: {role.title()}\n\n"
                            f"Log in here: {login_url}\n\n"
                            f"Please change your password after your first login."
                        ),
                    )
                    flash("User created and welcome email sent.", "success")
                except Exception:  # noqa: BLE001
                    flash("User created but the welcome email could not be sent.", "warning")
            else:
                flash("User created. Email delivery is not configured so no welcome email was sent.", "success")
            return redirect(url_for("users.list_view"))

    return render_template(
        "users/form.html",
        user_record=None,
        form_data=form_data,
        page_title="New User",
        submit_label="Create User",
        role_options=VALID_USER_ROLES,
    )


@users_bp.route("/<int:user_id>/send-reset", methods=["POST"])
@admin_required
def send_reset_view(user_id: int):
    user_record = get_user_by_id(user_id)
    if not user_record:
        flash("User not found.", "danger")
    elif not user_record.get("is_active"):
        flash("Activate this user before sending a password reset.", "warning")
    elif not smtp_configured():
        flash("Email delivery is not configured, so reset emails cannot be sent.", "warning")
    else:
        try:
            send_password_reset_email(
                user_record,
                requested_by=g.user["id"],
                requested_by_name=g.user["full_name"],
            )
            flash(f"Password reset email sent to {user_record['email']}.", "success")
        except Exception:
            current_app.logger.exception("Admin password reset email failed")
            flash("Password reset email could not be sent.", "warning")
    return redirect(url_for("users.list_view"))


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
        elif password and len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
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
