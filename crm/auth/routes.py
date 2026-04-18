from functools import wraps

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from bridge_crm.crm.auth.queries import (
    clear_login_attempts,
    count_recent_failed_attempts,
    get_user_by_email,
    record_login_attempt,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*roles):
    allowed_roles = {role.strip().lower() for role in roles if role}

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            user_role = (g.user or {}).get("role")
            if user_role not in allowed_roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard.index"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def admin_required(view):
    return roles_required("admin")(view)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        ip_address = ip_address.split(",")[0].strip()

        if count_recent_failed_attempts(
            ip_address, current_app.config["LOGIN_RATE_LIMIT_WINDOW_SECONDS"]
        ) >= current_app.config["LOGIN_RATE_LIMIT_COUNT"]:
            flash("Too many failed attempts. Try again in 15 minutes.", "danger")
            return render_template("auth/login.html"), 429

        user = get_user_by_email(email) if email else None
        if not user or not check_password_hash(user["password_hash"], password):
            record_login_attempt(email, ip_address, successful=False)
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html"), 401

        if not user["is_active"]:
            flash("Your account is inactive.", "danger")
            return render_template("auth/login.html"), 403

        clear_login_attempts(ip_address, email)
        record_login_attempt(email, ip_address, successful=True)
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["full_name"]
        next_url = request.args.get("next") or url_for("dashboard.index")
        return redirect(next_url)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
