from django.contrib.auth.models import Group, User
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .audit import get_current_request, log_audit_event


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    log_audit_event(
        action="LOGIN",
        model_name="Authentication",
        description=f"User '{user.username}' logged in.",
        user=user,
        target_id=user.pk,
        request=request,
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    username = user.username if user else "Unknown"
    user_id = user.pk if user else None
    log_audit_event(
        action="LOGOUT",
        model_name="Authentication",
        description=f"User '{username}' logged out.",
        user=user,
        target_id=user_id,
        request=request,
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    attempted_username = credentials.get("username", "Unknown")
    log_audit_event(
        action="LOGIN_FAILED",
        model_name="Authentication",
        description=f"Failed login attempt for username '{attempted_username}'.",
        target_id=attempted_username,
        request=request,
    )


@receiver(m2m_changed, sender=User.groups.through)
def on_user_groups_changed(sender, instance, action, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    actor = None
    request = get_current_request()
    if request and request.user.is_authenticated:
        actor = request.user

    if action == "post_clear":
        desc = f"All groups cleared from user '{instance.username}'."
        changed_group_ids = []
    elif action == "post_add":
        desc = f"Groups {sorted(pk_set)} assigned to user '{instance.username}'."
        changed_group_ids = sorted(pk_set)
    else:
        desc = f"Groups {sorted(pk_set)} removed from user '{instance.username}'."
        changed_group_ids = sorted(pk_set)

    log_audit_event(
        action="ROLE_CHANGE",
        model_name="User",
        description=desc,
        user=actor,
        target_id=instance.pk,
        after_data={"changed_group_ids": changed_group_ids},
        request=request,
    )


@receiver(m2m_changed, sender=User.user_permissions.through)
def on_user_permissions_changed(sender, instance, action, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    actor = None
    request = get_current_request()
    if request and request.user.is_authenticated:
        actor = request.user

    if action == "post_clear":
        desc = f"All direct permissions cleared from user '{instance.username}'."
        changed_permission_ids = []
    elif action == "post_add":
        desc = f"Permissions {sorted(pk_set)} assigned to user '{instance.username}'."
        changed_permission_ids = sorted(pk_set)
    else:
        desc = f"Permissions {sorted(pk_set)} removed from user '{instance.username}'."
        changed_permission_ids = sorted(pk_set)

    log_audit_event(
        action="PERMISSION_CHANGE",
        model_name="User",
        description=desc,
        user=actor,
        target_id=instance.pk,
        after_data={"changed_permission_ids": changed_permission_ids},
        request=request,
    )


@receiver(m2m_changed, sender=Group.permissions.through)
def on_group_permissions_changed(sender, instance, action, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    actor = None
    request = get_current_request()
    if request and request.user.is_authenticated:
        actor = request.user

    if action == "post_clear":
        desc = f"All permissions cleared from group '{instance.name}'."
        changed_permission_ids = []
    elif action == "post_add":
        desc = f"Permissions {sorted(pk_set)} assigned to group '{instance.name}'."
        changed_permission_ids = sorted(pk_set)
    else:
        desc = f"Permissions {sorted(pk_set)} removed from group '{instance.name}'."
        changed_permission_ids = sorted(pk_set)

    log_audit_event(
        action="PERMISSION_CHANGE",
        model_name="Group",
        description=desc,
        user=actor,
        target_id=instance.pk,
        after_data={"changed_permission_ids": changed_permission_ids},
        request=request,
    )
