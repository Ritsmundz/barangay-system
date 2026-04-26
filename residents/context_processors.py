import base64
from pathlib import Path

from .models import Notification
from .views import get_user_profile


_LOGO_DATA_URI = None
_HALL_DATA_URI = None
_OFFICIAL_DATA_URI = None
_SCHOOL_DATA_URI = None
_ROSA_SCHOOL_DATA_URI = None
_JOSE_SCHOOL_DATA_URI = None
_ACTIVITIES_DATA_URI = None
_EVENT1_DATA_URI = None
_EVENT2_DATA_URI = None
_EVENT3_DATA_URI = None


def _build_data_uri(path):
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    else:
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _read_first_image(candidates):
    base_dir = Path(__file__).resolve().parent / "static" / "residents" / "img"
    for name in candidates:
        image_path = base_dir / name
        try:
            if image_path.exists():
                return _build_data_uri(image_path)
        except OSError:
            return ""
    return ""


def _get_logo_data_uri():
    global _LOGO_DATA_URI
    if _LOGO_DATA_URI is not None:
        return _LOGO_DATA_URI

    _LOGO_DATA_URI = _read_first_image(["barangay-logo.jpg"])
    return _LOGO_DATA_URI


def _get_hall_data_uri():
    global _HALL_DATA_URI
    _HALL_DATA_URI = _read_first_image([
        "barangay gulod hall.webp",
        "barangay-gulod-hall.webp",
        "barangay-gulod-hall.png",
    ])
    return _HALL_DATA_URI


def _get_official_data_uri():
    global _OFFICIAL_DATA_URI
    if _OFFICIAL_DATA_URI is not None:
        return _OFFICIAL_DATA_URI

    _OFFICIAL_DATA_URI = _read_first_image([
        "captain.png",
        "rey-aldrin-s-tolentino.png",
        "rey-aldrin-s-tolentino.jpg",
        "rey-aldrin-s-tolentino.jpeg",
    ])
    return _OFFICIAL_DATA_URI


def _get_school_data_uri():
    global _SCHOOL_DATA_URI
    if _SCHOOL_DATA_URI is not None:
        return _SCHOOL_DATA_URI

    _SCHOOL_DATA_URI = _read_first_image([
        "rosa2.jpg",
        "rosa.jpg",
        "rosa-l-susano-elementary-school.png",
        "rosa-l-susano-elementary-school.jpg",
        "rosa-l-susano-elementary-school.jpeg",
    ])
    return _SCHOOL_DATA_URI


def _get_rosa_school_data_uri():
    global _ROSA_SCHOOL_DATA_URI
    if _ROSA_SCHOOL_DATA_URI is not None:
        return _ROSA_SCHOOL_DATA_URI

    _ROSA_SCHOOL_DATA_URI = _read_first_image([
        "rosa2.jpg",
        "rosa.jpg",
        "rosa-l-susano-elementary-school.png",
        "rosa-l-susano-elementary-school.jpg",
        "rosa-l-susano-elementary-school.jpeg",
    ])
    return _ROSA_SCHOOL_DATA_URI


def _get_jose_school_data_uri():
    global _JOSE_SCHOOL_DATA_URI
    if _JOSE_SCHOOL_DATA_URI is not None:
        return _JOSE_SCHOOL_DATA_URI

    _JOSE_SCHOOL_DATA_URI = _read_first_image([
        "jose.jpg",
        "jose.jpeg",
        "jose.png",
    ])
    return _JOSE_SCHOOL_DATA_URI


def _get_activities_data_uri():
    global _ACTIVITIES_DATA_URI
    if _ACTIVITIES_DATA_URI is not None:
        return _ACTIVITIES_DATA_URI

    _ACTIVITIES_DATA_URI = _read_first_image([
        "barangay-activities.png",
        "barangay-activities.jpg",
        "barangay-activities.jpeg",
        "barangay-events.png",
        "barangay-events.jpg",
        "barangay-events.jpeg",
    ])
    return _ACTIVITIES_DATA_URI


def _get_event1_data_uri():
    global _EVENT1_DATA_URI
    if _EVENT1_DATA_URI is not None:
        return _EVENT1_DATA_URI

    _EVENT1_DATA_URI = _read_first_image(["event1.jpg", "event1.jpeg", "event1.png"])
    return _EVENT1_DATA_URI


def _get_event2_data_uri():
    global _EVENT2_DATA_URI
    if _EVENT2_DATA_URI is not None:
        return _EVENT2_DATA_URI

    _EVENT2_DATA_URI = _read_first_image(["event2.jpg", "event2.jpeg", "event2.png"])
    return _EVENT2_DATA_URI


def _get_event3_data_uri():
    global _EVENT3_DATA_URI
    if _EVENT3_DATA_URI is not None:
        return _EVENT3_DATA_URI

    _EVENT3_DATA_URI = _read_first_image(["event3.jpg", "event3.jpeg", "event3.png"])
    return _EVENT3_DATA_URI


def app_shell(request):
    logo_data_uri = _get_logo_data_uri()
    hall_data_uri = _get_hall_data_uri()
    official_data_uri = _get_official_data_uri()
    school_data_uri = _get_school_data_uri()
    rosa_school_data_uri = _get_rosa_school_data_uri()
    jose_school_data_uri = _get_jose_school_data_uri()
    activities_data_uri = _get_activities_data_uri()
    event1_data_uri = _get_event1_data_uri()
    event2_data_uri = _get_event2_data_uri()
    event3_data_uri = _get_event3_data_uri()
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "user_profile": None,
            "user_display_name": "",
            "primary_role": "",
            "barangay_logo_data_uri": logo_data_uri,
            "barangay_hall_data_uri": hall_data_uri,
            "barangay_official_data_uri": official_data_uri,
            "barangay_school_data_uri": school_data_uri,
            "rosa_school_data_uri": rosa_school_data_uri,
            "jose_school_data_uri": jose_school_data_uri,
            "barangay_activities_data_uri": activities_data_uri,
            "barangay_event1_data_uri": event1_data_uri,
            "barangay_event2_data_uri": event2_data_uri,
            "barangay_event3_data_uri": event3_data_uri,
            "resident_notifications": [],
            "resident_unread_notifications_count": 0,
        }

    user_profile = get_user_profile(user)
    if user_profile and user_profile.resident:
        resident = user_profile.resident
        display_name = " ".join(
            part
            for part in [
                resident.first_name,
                f"{resident.middle_name[:1]}." if resident.middle_name else "",
                resident.last_name,
                resident.suffix or "",
            ]
            if part
        )
    elif user_profile:
        display_name = " ".join(part for part in [user_profile.first_name, user_profile.last_name] if part).strip()
    else:
        display_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip() or user.username

    primary_role = user.groups.values_list("name", flat=True).first() or ("Administrator" if user.is_superuser else "Staff")

    resident_notifications = []
    resident_unread_notifications_count = 0
    if user.groups.filter(name="Resident").exists():
        resident_notifications = list(
            Notification.objects.filter(user=user)
            .order_by("-created_at")[:6]
        )
        resident_unread_notifications_count = sum(1 for item in resident_notifications if not item.is_read)
        if resident_unread_notifications_count == 0:
            resident_unread_notifications_count = Notification.objects.filter(user=user, is_read=False).count()

    return {
        "user_profile": user_profile,
        "user_display_name": display_name,
        "primary_role": primary_role,
        "barangay_logo_data_uri": logo_data_uri,
        "barangay_hall_data_uri": hall_data_uri,
        "barangay_official_data_uri": official_data_uri,
        "barangay_school_data_uri": school_data_uri,
        "rosa_school_data_uri": rosa_school_data_uri,
        "jose_school_data_uri": jose_school_data_uri,
        "barangay_activities_data_uri": activities_data_uri,
        "barangay_event1_data_uri": event1_data_uri,
        "barangay_event2_data_uri": event2_data_uri,
        "barangay_event3_data_uri": event3_data_uri,
        "resident_notifications": resident_notifications,
        "resident_unread_notifications_count": resident_unread_notifications_count,
    }
