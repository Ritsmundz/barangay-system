import json
import logging
from threading import local

from django.core.files.base import File
from django.db import DatabaseError
from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import AuditLog

_state = local()
logger = logging.getLogger(__name__)


def set_current_request(request):
    _state.request = request


def get_current_request():
    return getattr(_state, "request", None)


def clear_current_request():
    if hasattr(_state, "request"):
        delattr(_state, "request")


def get_client_ip(request):
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _json_safe(data):
    if data is None:
        return None
    if isinstance(data, dict):
        return {key: _json_safe(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_json_safe(value) for value in data]
    if isinstance(data, File):
        return getattr(data, "name", str(data)) or ""
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def snapshot_instance(instance):
    if instance is None:
        return None
    data = model_to_dict(instance)
    data["id"] = instance.pk
    return _json_safe(data)


def log_audit_event(
    *,
    action,
    model_name,
    description,
    user=None,
    target_id=None,
    before_data=None,
    after_data=None,
    request=None,
):
    request = request or get_current_request()

    if user is None and request and getattr(request, "user", None) and request.user.is_authenticated:
        user = request.user

    ip_address = get_client_ip(request) if request else None
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""
    request_path = request.path[:255] if request else ""

    try:
        AuditLog.objects.create(
            user=user,
            action=action,
            model_name=model_name,
            description=description,
            target_id=str(target_id) if target_id is not None else None,
            before_data=_json_safe(before_data),
            after_data=_json_safe(after_data),
            ip_address=ip_address,
            user_agent=user_agent,
            request_path=request_path,
        )
    except DatabaseError:
        # Audit logging should never break request flow (e.g., during fresh deploys
        # where migrations are not yet fully applied).
        logger.exception("Audit log write failed; continuing request.")
