from flask import Blueprint, g, redirect, render_template, request, url_for

from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.notifications.queries import (
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
)

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.route("/")
@login_required
def list_view():
    filter_name = request.args.get("filter", "all").strip().lower()
    unread_only = filter_name == "unread"
    notifications = list_notifications_for_user(g.user["id"], unread_only=unread_only)
    return render_template(
        "notifications/list.html",
        notifications=notifications,
        active_filter="unread" if unread_only else "all",
    )


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def read_view(notification_id: int):
    mark_notification_read(notification_id, g.user["id"])
    next_url = request.form.get("next", "").strip() or url_for("notifications.list_view")
    return redirect(next_url)


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all_view():
    mark_all_notifications_read(g.user["id"])
    next_url = request.form.get("next", "").strip() or url_for("notifications.list_view")
    return redirect(next_url)
