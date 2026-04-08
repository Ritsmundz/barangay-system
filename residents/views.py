from calendar import month
from datetime import date
import csv
import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from functools import wraps
from django.http import HttpResponse
from django.http import JsonResponse
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.db.models.functions import ExtractMonth
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import Group, User
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Resident, Household, ServiceRequest, Payment, Complaint, ServiceType, Purok, AuditLog, RequestPurpose, UserProfile
from .forms import (
    ResidentForm,
    HouseholdForm,
    ComplaintForm,
    ClearanceRequestForm,
    ResidentPortalRegistrationForm,
    ResidentVerificationCreateForm,
)
from .audit import log_audit_event, snapshot_instance

def is_captain(user):
    return user.groups.filter(name='Captain').exists()

def is_secretary(user):
    return user.groups.filter(name='Secretary').exists()


def is_treasurer(user):
    return user.groups.filter(name='Treasurer').exists()


def is_staff_group_user(user):
    return user.groups.filter(name='Staff').exists()


def is_staff_user(user):
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=["Captain", "Secretary", "Treasurer", "Staff"]).exists()


def can_create_service_requests(user):
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=["Secretary", "Staff"]).exists()


def is_resident(user):
    return user.groups.filter(name="Resident").exists()


def group_required(test_func):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if test_func(request.user):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("You do not have permission to access this page.")
        return _wrapped_view
    return decorator


def get_user_profile(user):
    return UserProfile.objects.filter(user=user).select_related("resident").first()


def _extract_resident_data_from_ocr(text):
    cleaned = re.sub(r"\r", "", text or "")
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    upper_text = cleaned.upper()
    data = {}

    def find_value_after_label(label_pattern):
        for ln in lines:
            match = re.search(label_pattern + r"\s*[:\-]?\s*(.+)$", ln, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def normalize_date(raw):
        if not raw:
            return None
        raw = raw.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            return raw
        m = re.match(r"^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$", raw)
        if m:
            yyyy, mm, dd = m.groups()
            return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
        m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", raw)
        if m:
            mm, dd, yyyy = m.groups()
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2})$", raw)
        if m:
            mm, dd, yy = m.groups()
            yyyy = int(yy) + (2000 if int(yy) < 50 else 1900)
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"

        month_map = {
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        }
        m = re.match(r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})\s+(\d{4})$", raw.upper())
        if m:
            mon, dd, yyyy = m.groups()
            mm = month_map[mon[:3]]
            return f"{yyyy}-{mm:02d}-{int(dd):02d}"
        return None

    first_name = find_value_after_label(r"first\s*name")
    middle_name = find_value_after_label(r"middle\s*name")
    last_name = find_value_after_label(r"last\s*name")
    suffix = find_value_after_label(r"suffix")
    birth_place = find_value_after_label(r"(birth\s*place|birthplace)")
    civil_status = find_value_after_label(r"civil\s*status")
    precinct = find_value_after_label(r"(precinct|precint)")
    nationality = find_value_after_label(r"nationality")
    religion = find_value_after_label(r"religion")

    sex = find_value_after_label(r"(sex|gender)")
    if sex:
        sex = sex.strip().capitalize()
        if sex not in ("Male", "Female"):
            sex = None
    if not sex:
        if re.search(r"\bSEX\b.*\bMALE\b", upper_text) or re.search(r"\bGENDER\b.*\bMALE\b", upper_text):
            sex = "Male"
        elif re.search(r"\bSEX\b.*\bFEMALE\b", upper_text) or re.search(r"\bGENDER\b.*\bFEMALE\b", upper_text):
            sex = "Female"
        elif re.search(r"\bSEX\b\s*[:\-]?\s*M\b", upper_text):
            sex = "Male"
        elif re.search(r"\bSEX\b\s*[:\-]?\s*F\b", upper_text):
            sex = "Female"

    if not civil_status:
        if "SINGLE" in upper_text:
            civil_status = "Single"
        elif "MARRIED" in upper_text:
            civil_status = "Married"
        elif "WIDOWED" in upper_text:
            civil_status = "Widowed"
        elif "SEPARATED" in upper_text:
            civil_status = "Separated"
        elif "DIVORCED" in upper_text:
            civil_status = "Divorced"

    raw_birth_date = (
        find_value_after_label(r"(birth\s*date|date\s*of\s*birth|birthdate)")
        or next((ln for ln in lines if re.search(r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}", ln)), None)
    )
    if raw_birth_date and ":" in raw_birth_date:
        raw_birth_date = raw_birth_date.split(":", 1)[-1].strip()
    birth_date = normalize_date(raw_birth_date)
    if not birth_date:
        m = re.search(r"\b(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})\b", cleaned)
        if m:
            birth_date = normalize_date(m.group(1))
    if not birth_date:
        m = re.search(r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b", cleaned)
        if m:
            birth_date = normalize_date(m.group(1))
    if not birth_date:
        m = re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{1,2}\s+\d{4}\b", upper_text)
        if m:
            birth_date = normalize_date(m.group(0))

    if not (first_name and last_name):
        full_name_line = find_value_after_label(r"name")
        if full_name_line and not (first_name and last_name):
            parts = [p for p in re.split(r"\s+", full_name_line) if p]
            if len(parts) >= 2:
                if not first_name:
                    first_name = parts[0]
                if not last_name:
                    last_name = parts[-1]
                if len(parts) > 2 and not middle_name:
                    middle_name = " ".join(parts[1:-1])
    if not (first_name and last_name):
        candidate_lines = []
        noise_words = {"REPUBLIC", "PHILIPPINES", "ADDRESS", "BIRTH", "SEX", "GENDER", "CIVIL", "STATUS", "NATIONALITY", "ID", "CARD"}
        for ln in lines[:8]:
            if re.search(r"\d", ln):
                continue
            tokens = [t for t in re.split(r"\s+", ln.upper()) if t]
            if len(tokens) < 2:
                continue
            if any(tok in noise_words for tok in tokens):
                continue
            candidate_lines.append(ln)

        if candidate_lines:
            raw_name = max(candidate_lines, key=len)
            if "," in raw_name:
                left, right = raw_name.split(",", 1)
                last_name = last_name or left.strip().title()
                right_parts = [p for p in re.split(r"\s+", right.strip()) if p]
                if right_parts:
                    first_name = first_name or right_parts[0].title()
                if len(right_parts) > 1:
                    middle_name = middle_name or " ".join(p.title() for p in right_parts[1:])
            else:
                name_parts = [p for p in re.split(r"\s+", raw_name.strip()) if p]
                if len(name_parts) >= 2:
                    first_name = first_name or name_parts[0].title()
                    last_name = last_name or name_parts[-1].title()
                    if len(name_parts) > 2:
                        middle_name = middle_name or " ".join(p.title() for p in name_parts[1:-1])

    if first_name:
        data["first_name"] = first_name
    if middle_name:
        data["middle_name"] = middle_name
    if last_name:
        data["last_name"] = last_name
    if suffix:
        data["suffix"] = suffix
    if birth_date:
        data["birth_date"] = birth_date
    if birth_place:
        data["place_of_birth"] = birth_place
    if sex:
        data["gender"] = sex
    if civil_status:
        data["civil_status"] = civil_status
    if precinct:
        data["precinct"] = precinct
    if nationality:
        data["nationality"] = nationality
    if religion:
        data["religion"] = religion

    qcid_data = _extract_qcid_data_from_ocr(cleaned)
    for key, value in qcid_data.items():
        if value:
            data[key] = value

    data = _normalize_extracted_name_fields(data, cleaned)
    data = _remove_address_like_name_noise(data)

    return data


def _try_decode_qr_payloads(image):
    payloads = []
    qr_detected = False
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"payloads": payloads, "qr_detected": qr_detected}

    try:
        rgb = image.convert("RGB")
        arr = np.array(rgb)
        detector = cv2.QRCodeDetector()

        # Try multiple variants to improve decode reliability for cropped QR images.
        variants = [arr]
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        variants.append(cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB))
        variants.append(cv2.cvtColor(cv2.equalizeHist(gray), cv2.COLOR_GRAY2RGB))
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(cv2.cvtColor(bw, cv2.COLOR_GRAY2RGB))
        h, w = gray.shape[:2]
        up2 = cv2.resize(arr, (max(1, w * 2), max(1, h * 2)), interpolation=cv2.INTER_CUBIC)
        variants.append(up2)

        for variant in variants:
            bgr = cv2.cvtColor(variant, cv2.COLOR_RGB2BGR)

            detected, points = detector.detect(bgr)
            if detected and points is not None:
                qr_detected = True

            data, points_single, _ = detector.detectAndDecode(bgr)
            if points_single is not None:
                qr_detected = True
            if data and data not in payloads:
                payloads.append(data)

            ok, decoded_info, points_multi, _ = detector.detectAndDecodeMulti(bgr)
            if points_multi is not None:
                qr_detected = True
            if ok and decoded_info:
                for d in decoded_info:
                    if d and d not in payloads:
                        payloads.append(d)
    except Exception:
        return {"payloads": payloads, "qr_detected": qr_detected}
    return {"payloads": payloads, "qr_detected": qr_detected}


def _extract_resident_data_from_qr_payload(payload):
    if not payload:
        return {}

    data = {}
    raw = payload.strip()

    # 1) JSON payload
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            for src, dst in {
                "first_name": "first_name",
                "middle_name": "middle_name",
                "last_name": "last_name",
                "suffix": "suffix",
                "birth_date": "birth_date",
                "birthdate": "birth_date",
                "gender": "gender",
                "sex": "gender",
                "civil_status": "civil_status",
                "place_of_birth": "place_of_birth",
                "birth_place": "place_of_birth",
                "precinct": "precinct",
                "precint": "precinct",
                "nationality": "nationality",
                "religion": "religion",
            }.items():
                val = obj.get(src)
                if val:
                    data[dst] = str(val).strip()
    except Exception:
        pass

    # 2) URL query payload
    if not data and ("?" in raw and ("http://" in raw.lower() or "https://" in raw.lower())):
        try:
            parsed = urlparse(raw)
            q = parse_qs(parsed.query)
            for src, dst in {
                "first_name": "first_name",
                "middle_name": "middle_name",
                "last_name": "last_name",
                "suffix": "suffix",
                "birth_date": "birth_date",
                "birthdate": "birth_date",
                "gender": "gender",
                "sex": "gender",
                "civil_status": "civil_status",
                "place_of_birth": "place_of_birth",
                "birth_place": "place_of_birth",
                "precinct": "precinct",
                "precint": "precinct",
                "nationality": "nationality",
                "religion": "religion",
            }.items():
                if src in q and q[src]:
                    data[dst] = q[src][0].strip()
        except Exception:
            pass

    # 3) key:value text payload
    if not data and "|" in raw:
        # 3) Pipe-delimited QCID-like payload
        # Example:
        # LAST, FIRST MIDDLE|IDNO|CIVIL_CODE|YYMMDD|SEX|...|ISSUE_YYMMDD|
        parts = [p.strip() for p in raw.split("|")]
        if parts and "," in parts[0]:
            name_part = parts[0]
            last, rest = [p.strip() for p in name_part.split(",", 1)]
            name_tokens = [t.strip(". ") for t in rest.split() if t.strip(". ")]
            if last:
                data["last_name"] = last.title()
            if name_tokens:
                # QCID case: "JOHN RICHMOND P." -> first_name="John Richmond", middle_name="P"
                if len(name_tokens) >= 2 and len(name_tokens[-1]) <= 2:
                    data["first_name"] = " ".join(t.title() for t in name_tokens[:-1])
                    data["middle_name"] = name_tokens[-1].title()
                else:
                    data["first_name"] = name_tokens[0].title()
                    if len(name_tokens) > 1:
                        data["middle_name"] = " ".join(t.title() for t in name_tokens[1:])

            if len(parts) > 3 and re.match(r"^\d{6}$", parts[3]):
                yymmdd = parts[3]
                yy = int(yymmdd[0:2])
                mm = int(yymmdd[2:4])
                dd = int(yymmdd[4:6])
                yyyy = 2000 + yy if yy <= 30 else 1900 + yy
                data["birth_date"] = f"{yyyy:04d}-{mm:02d}-{dd:02d}"

            if len(parts) > 4:
                sex = parts[4].upper()
                if sex in {"M", "MALE"}:
                    data["gender"] = "Male"
                elif sex in {"F", "FEMALE"}:
                    data["gender"] = "Female"

            if len(parts) > 2:
                civil_code = parts[2].strip()
                civil_map = {
                    "1": "Single",
                    "2": "Married",
                    "3": "Widowed",
                    "4": "Separated",
                    "5": "Divorced",
                }
                if civil_code in civil_map:
                    data["civil_status"] = civil_map[civil_code]

    # 4) key:value text payload
    if not data:
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key_n = re.sub(r"[^a-z0-9]", "", key.lower())
            val = val.strip()
            key_map = {
                "firstname": "first_name",
                "middlename": "middle_name",
                "lastname": "last_name",
                "suffix": "suffix",
                "birthdate": "birth_date",
                "dateofbirth": "birth_date",
                "gender": "gender",
                "sex": "gender",
                "civilstatus": "civil_status",
                "birthplace": "place_of_birth",
                "placeofbirth": "place_of_birth",
                "precinct": "precinct",
                "precint": "precinct",
                "nationality": "nationality",
                "religion": "religion",
            }
            if key_n in key_map and val:
                data[key_map[key_n]] = val

    # Normalize common values
    if "gender" in data:
        g = data["gender"].strip().upper()
        if g in {"M", "MALE"}:
            data["gender"] = "Male"
        elif g in {"F", "FEMALE"}:
            data["gender"] = "Female"

    if "birth_date" in data:
        normalized = _extract_resident_data_from_ocr(f"birthdate: {data['birth_date']}").get("birth_date")
        if normalized:
            data["birth_date"] = normalized

    return _normalize_extracted_name_fields(data, raw)


def _extract_qcid_data_from_ocr(text):
    cleaned = text or ""
    upper_text = cleaned.upper()
    if "QCID" not in upper_text and "QUEZON CITY" not in upper_text and "QC ID" not in upper_text:
        return {}

    lines = [ln.strip() for ln in re.sub(r"\r", "", cleaned).split("\n") if ln.strip()]

    def normalize(s):
        s = s.upper()
        s = s.replace("0", "O").replace("1", "I").replace("5", "S")
        return re.sub(r"[^A-Z0-9]", "", s)

    norm_lines = [normalize(ln) for ln in lines]

    aliases = {
        "first_name": ["FIRSTNAME", "GIVENNAME"],
        "middle_name": ["MIDDLENAME", "MIDNAME", "MIDDLEINITIAL"],
        "last_name": ["LASTNAME", "SURNAME", "FAMILYNAME"],
        "birth_date": ["BIRTHDATE", "DATEOFBIRTH", "DOB"],
        "place_of_birth": ["BIRTHPLACE", "PLACEOFBIRTH", "POB"],
        "gender": ["SEX", "GENDER"],
        "civil_status": ["CIVILSTATUS"],
        "precinct": ["PRECINCT", "PRECINT"],
    }
    all_labels = [a for group in aliases.values() for a in group]

    def has_any_label(norm_line):
        return any(lbl in norm_line for lbl in all_labels)

    def normalize_date(raw):
        if not raw:
            return None
        raw = raw.strip()
        m = re.search(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", raw)
        if m:
            parts = re.split(r"[\/\-]", m.group(1))
            mm, dd, yy = parts
            yyyy = int(yy)
            if yyyy < 100:
                yyyy += 2000 if yyyy < 50 else 1900
            return f"{yyyy:04d}-{int(mm):02d}-{int(dd):02d}"
        m = re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})\s+(\d{4})", raw.upper())
        if m:
            months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
            mon, dd, yyyy = m.groups()
            return f"{int(yyyy):04d}-{months[mon[:3]]:02d}-{int(dd):02d}"
        return None

    def extract_value_for(field_key):
        label_variants = aliases[field_key]
        for idx, norm_line in enumerate(norm_lines):
            matched_label = next((lbl for lbl in label_variants if lbl in norm_line), None)
            if not matched_label:
                continue

            original_line = lines[idx]
            inline = re.split(r"[:\-]", original_line, maxsplit=1)
            if len(inline) == 2 and inline[1].strip():
                return inline[1].strip()

            if idx + 1 < len(lines):
                nxt_norm = norm_lines[idx + 1]
                if not has_any_label(nxt_norm):
                    return lines[idx + 1].strip()
        return None

    data = {}

    # Strong-name line pattern on QCID:
    # "SARMIENTO, JOHN RICHMOND PAGADUAN"
    for ln in lines:
        if "," not in ln:
            continue
        if re.search(r"\d", ln):
            continue
        if len(ln) < 8:
            continue
        upper_ln = ln.upper()
        if any(x in upper_ln for x in ["STREET", "QUEZON", "CITY", "BARANGAY", "BLOOD TYPE", "DATE ISSUED", "VALID UNTIL"]):
            continue
        left, right = ln.split(",", 1)
        left_clean = re.sub(r"[^A-Za-z\-\s]", "", left).strip()
        right_tokens = [re.sub(r"[^A-Za-z\-\s]", "", t).strip() for t in right.strip().split()]
        right_tokens = [t for t in right_tokens if t]
        if left_clean and right_tokens:
            # For QCID, treat last token as middle name (often middle surname),
            # everything before that is first name.
            if len(right_tokens) >= 2:
                data["first_name"] = " ".join(t.title() for t in right_tokens[:-1]).strip()
                data["middle_name"] = right_tokens[-1].title()
            else:
                data["first_name"] = right_tokens[0].title()
            data["last_name"] = left_clean.title()
            break
    for field in aliases:
        if data.get(field):
            continue
        val = extract_value_for(field)
        if not val:
            continue
        if field == "gender":
            v = val.upper()
            if re.search(r"\bMALE\b", v) or re.search(r"\bM\b", v):
                data[field] = "Male"
            elif re.search(r"\bFEMALE\b", v) or re.search(r"\bF\b", v):
                data[field] = "Female"
        elif field == "civil_status":
            v = val.upper()
            if "SINGLE" in v:
                data[field] = "Single"
            elif "MARRIED" in v:
                data[field] = "Married"
            elif "WIDOW" in v:
                data[field] = "Widowed"
            elif "SEPARAT" in v:
                data[field] = "Separated"
            elif "DIVORC" in v:
                data[field] = "Divorced"
            else:
                data[field] = val.title()
        elif field == "birth_date":
            dt = normalize_date(val)
            if dt:
                data[field] = dt
        else:
            data[field] = val.title() if field.endswith("name") else val

    if not data.get("first_name") and not data.get("last_name"):
        for ln in lines:
            if "," in ln and len(ln) > 6:
                left, right = ln.split(",", 1)
                left = left.strip()
                right_parts = [p for p in right.strip().split() if p]
                if left and right_parts:
                    data["last_name"] = left.title()
                    data["first_name"] = right_parts[0].title()
                    if len(right_parts) > 1:
                        data["middle_name"] = " ".join(p.title() for p in right_parts[1:])
                    break

    data = _remove_address_like_name_noise(data)
    return data


def _normalize_extracted_name_fields(data, source_text=""):
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    def clean_token(token):
        token = re.sub(r"\s+", " ", token).strip(" ,.-")
        return token

    first_name = clean_token(first_name)
    middle_name = clean_token(middle_name)
    last_name = clean_token(last_name)

    # Case: OCR copied the same full name into multiple fields.
    same_nonempty = (
        first_name and middle_name and last_name and
        first_name.upper() == middle_name.upper() == last_name.upper()
    )
    if same_nonempty:
        full = first_name
        if "," in full:
            ln, rest = [p.strip() for p in full.split(",", 1)]
            parts = [p for p in rest.split() if p]
            data["last_name"] = ln.title() if ln else ""
            data["first_name"] = parts[0].title() if parts else ""
            data["middle_name"] = " ".join(p.title() for p in parts[1:]) if len(parts) > 1 else ""
            return data
        parts = [p for p in full.split() if p]
        if len(parts) >= 2:
            data["first_name"] = parts[0].title()
            data["last_name"] = parts[-1].title()
            data["middle_name"] = " ".join(p.title() for p in parts[1:-1]) if len(parts) > 2 else ""
            return data

    # Case: first_name contains full name while middle/last are missing or partial.
    if first_name:
        parts = [p for p in first_name.split() if p]
        if len(parts) >= 2:
            # If last_name is missing or appears only as part of full string, derive from parts.
            if not last_name or (last_name and last_name.upper() in first_name.upper() and len(last_name) <= 3):
                data["last_name"] = parts[-1].title()
            # If middle name appears to be full name, recompute.
            if not middle_name or middle_name.upper() == first_name.upper():
                data["middle_name"] = " ".join(p.title() for p in parts[1:-1]) if len(parts) > 2 else ""
            # Keep first token as first name when it looks like full-name stuffing.
            if first_name.upper() == " ".join(parts).upper():
                data["first_name"] = parts[0].title()

    # Case: first name got split into first+middle fragments (e.g., "JER" + "MIE").
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    if first_name and middle_name:
        if len(first_name) <= 4 and len(middle_name) <= 6:
            merged = f"{first_name}{middle_name}"
            if re.match(r"^[A-Za-z]+$", merged):
                data["first_name"] = merged.title()
                data["middle_name"] = ""

    # QCID/common OCR case: compound first name split across first/middle
    # when no explicit middle-name label is detected in OCR text.
    first_name = (data.get("first_name") or "").strip()
    middle_name = (data.get("middle_name") or "").strip()
    if source_text and first_name and middle_name:
        upper_source = source_text.upper()
        has_middle_label = (
            "MIDDLE NAME" in upper_source
            or "MIDDLENAME" in re.sub(r"[^A-Z]", "", upper_source)
            or "MIDDLE INITIAL" in upper_source
        )
        if not has_middle_label:
            if (
                len(first_name) <= 6
                and len(middle_name) >= 4
                and re.match(r"^[A-Za-z\- ]+$", first_name)
                and re.match(r"^[A-Za-z\- ]+$", middle_name)
            ):
                data["first_name"] = f"{first_name} {middle_name}".title()
                data["middle_name"] = ""

    # Case: last_name accidentally truncated but present in first_name full string.
    last_name = (data.get("last_name") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    if first_name and last_name and len(last_name) <= 3:
        fparts = [p for p in first_name.split() if p]
        if len(fparts) >= 2:
            data["last_name"] = fparts[-1].title()
            data["first_name"] = fparts[0].title()
            data["middle_name"] = " ".join(p.title() for p in fparts[1:-1]) if len(fparts) > 2 else data.get("middle_name", "")

    # Expand truncated surname using OCR text tokens (e.g., "iento" -> "sarmiento").
    last_name = (data.get("last_name") or "").strip()
    if source_text and last_name and len(last_name) >= 4:
        upper_fragment = re.sub(r"[^A-Z]", "", last_name.upper())
        tokens = re.findall(r"[A-Z]{4,}", source_text.upper())
        candidates = [
            t for t in tokens
            if t.endswith(upper_fragment) and len(t) > len(upper_fragment)
        ]
        if candidates:
            best = max(candidates, key=len)
            data["last_name"] = best.title()

    # If OCR has an obvious "LAST, FIRST MIDDLE" line, prefer it.
    if source_text:
        lines = [ln.strip() for ln in re.sub(r"\r", "", source_text).split("\n") if ln.strip()]
        comma_lines = [ln for ln in lines if "," in ln and not re.search(r"\d", ln)]
        if comma_lines:
            raw = max(comma_lines, key=len)
            left, right = raw.split(",", 1)
            ln = re.sub(r"[^A-Za-z\- ]", "", left).strip()
            rp = [re.sub(r"[^A-Za-z\-]", "", p).strip() for p in right.split()]
            rp = [p for p in rp if p]
            if ln and rp:
                data["last_name"] = ln.title()
                upper_source = source_text.upper()
                is_qcid_context = "QCID" in upper_source or "QUEZON CITY" in upper_source or "QC ID" in upper_source
                if is_qcid_context and len(rp) >= 2:
                    data["first_name"] = " ".join(p.title() for p in rp[:-1]).strip()
                    data["middle_name"] = rp[-1].title()
                else:
                    data["first_name"] = rp[0].title()
                    data["middle_name"] = " ".join(p.title() for p in rp[1:]) if len(rp) > 1 else ""

    # Final QCID-oriented cleanup:
    # remove symbol noise in names and try rebuilding from "LAST, FIRST MIDDLE" segment.
    def clean_name_value(v):
        v = re.sub(r"[^A-Za-z\-\s']", " ", v or "")
        v = re.sub(r"\s+", " ", v).strip()
        return v

    data["first_name"] = clean_name_value(data.get("first_name", ""))
    data["middle_name"] = clean_name_value(data.get("middle_name", ""))
    data["last_name"] = clean_name_value(data.get("last_name", ""))

    if data.get("middle_name", "").upper() in {"", "AND"}:
        data["middle_name"] = ""

    if source_text and data.get("last_name"):
        ln_upper = re.escape(data["last_name"].upper())
        m = re.search(ln_upper + r"\s*,\s*([A-Z .&'-]+)", source_text.upper())
        if m:
            right = m.group(1)
            right_clean = re.sub(r"[^A-Z\s'-]", " ", right)
            tokens = [t for t in right_clean.split() if t]
            if len(tokens) >= 2:
                # Prefer compound first name + trailing middle token for QCID formats.
                rebuilt_first = " ".join(t.title() for t in tokens[:-1]).strip()
                rebuilt_middle = tokens[-1].title()
                if rebuilt_first:
                    data["first_name"] = rebuilt_first
                if rebuilt_middle and len(rebuilt_middle) <= 12:
                    data["middle_name"] = rebuilt_middle

    # If first name looks like clipped token (e.g., Johnp), keep only alphabetic chunk.
    if data.get("first_name"):
        fn = data["first_name"]
        if re.match(r"^[A-Za-z]{5,}$", fn) and fn[-1].islower() is False:
            pass
        # Remove trailing single-char artifact when middle is empty and token looks suspicious.
        if " " not in fn and len(fn) >= 5 and not data.get("middle_name"):
            data["first_name"] = re.sub(r"[^A-Za-z]", "", fn).title()

    return data


def _remove_address_like_name_noise(data):
    def is_address_like(value):
        if not value:
            return False
        up = value.upper()
        if re.search(r"\d", up):
            return True
        address_keywords = [
            "STREET", "ST", "ROAD", "RD", "AVE", "AVENUE", "CITY",
            "QUEZON", "BARANGAY", "PASONG", "TAMO", "MACAYA",
        ]
        return any(k in up for k in address_keywords)

    for key in ["first_name", "middle_name", "last_name"]:
        val = (data.get(key) or "").strip()
        if is_address_like(val):
            data[key] = ""

    return data


def _build_ocr_variants(image):
    from PIL import ImageOps, ImageFilter, ImageEnhance

    variants = []
    base = image.convert("RGB")
    variants.append(("original", base))

    gray = ImageOps.grayscale(base)
    variants.append(("gray", gray))

    auto = ImageOps.autocontrast(gray)
    variants.append(("autocontrast", auto))

    sharp = auto.filter(ImageFilter.SHARPEN)
    variants.append(("sharpen", sharp))

    high_contrast = ImageEnhance.Contrast(auto).enhance(2.0)
    variants.append(("high_contrast", high_contrast))

    bw = high_contrast.point(lambda px: 255 if px > 150 else 0)
    variants.append(("threshold_bw", bw))

    w, h = base.size
    upscale = base.resize((max(1, int(w * 1.8)), max(1, int(h * 1.8))))
    variants.append(("upscale", upscale))

    return variants


def _best_ocr_extraction(image, pytesseract):
    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 4",
        "--oem 3 --psm 11",
    ]

    best = {
        "score": -1,
        "text": "",
        "data": {},
    }
    results = []

    variants = _build_ocr_variants(image)
    for _, img_variant in variants:
        for cfg in configs:
            try:
                text = pytesseract.image_to_string(img_variant, lang="eng", config=cfg)
            except Exception:
                continue
            data = _extract_resident_data_from_ocr(text)
            score = len(data.keys())

            if data.get("first_name"):
                score += 1
            if data.get("last_name"):
                score += 1
            if data.get("birth_date"):
                score += 1
            if data.get("gender"):
                score += 2
            if data.get("civil_status"):
                score += 2
            if data.get("precinct"):
                score += 2

            # Penalize results that only contain name-like fields.
            if data and set(data.keys()).issubset({"first_name", "middle_name", "last_name", "suffix"}):
                score -= 2

            results.append({
                "score": score,
                "text": text,
                "data": data,
            })

            if score > best["score"]:
                best = {
                    "score": score,
                    "text": text,
                    "data": data,
                }

    # Merge fields from top OCR passes so we don't lose non-name fields
    # when one pass is strong on names but weak on demographics.
    merged = {}
    for res in sorted(results, key=lambda r: r["score"], reverse=True)[:10]:
        for key, value in (res["data"] or {}).items():
            if not value:
                continue
            if key not in merged:
                merged[key] = value
                continue

            # Prefer longer values for likely truncated names/places.
            if key in {"first_name", "middle_name", "last_name", "place_of_birth"}:
                if len(str(value)) > len(str(merged[key])):
                    merged[key] = value

    merged = _normalize_extracted_name_fields(merged, best["text"])
    return {
        "score": best["score"],
        "text": best["text"],
        "data": merged,
    }


@group_required(is_staff_user)
def scan_resident_id(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Invalid request method."}, status=405)

    id_image = request.FILES.get("id_image")
    if not id_image:
        return JsonResponse({"ok": False, "error": "No ID image uploaded."}, status=400)

    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return JsonResponse({
            "ok": False,
            "error": "OCR engine is not installed. Install 'pytesseract' and 'Pillow'.",
        }, status=500)

    tesseract_bin = shutil.which("tesseract")
    if not tesseract_bin:
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in common_paths:
            if Path(candidate).exists():
                tesseract_bin = candidate
                break

    if tesseract_bin:
        pytesseract.pytesseract.tesseract_cmd = tesseract_bin
    else:
        return JsonResponse({
            "ok": False,
            "error": (
                "Tesseract OCR is not installed. Install Tesseract and add it to PATH, "
                "or install to C:\\Program Files\\Tesseract-OCR\\tesseract.exe."
            ),
        }, status=500)

    try:
        image = Image.open(id_image)
        qr_result = _try_decode_qr_payloads(image)
        qr_payloads = qr_result.get("payloads", [])
        qr_detected = qr_result.get("qr_detected", False)
        qr_data = {}
        for payload in qr_payloads:
            parsed = _extract_resident_data_from_qr_payload(payload)
            for k, v in parsed.items():
                if v and k not in qr_data:
                    qr_data[k] = v

        # If a QR is clearly detected but cannot be decoded, don't OCR fallback
        # because OCR on QR modules produces garbage names.
        if qr_detected and not qr_data:
            return JsonResponse({
                "ok": False,
                "error": (
                    "QR code detected but could not be decoded. "
                    "Try recropping tighter around the QR, keep it straight, and use a clearer image."
                ),
            }, status=422)

        best = _best_ocr_extraction(image, pytesseract)
        ocr_text = best["text"]
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read image: {exc}"}, status=500)

    extracted = best["data"] if best else {}
    # Prefer QR values when available, then fill gaps from OCR.
    if qr_data:
        merged = dict(qr_data)
        for k, v in (extracted or {}).items():
            if k not in merged and v:
                merged[k] = v
        extracted = merged

    if not extracted:
        preview = re.sub(r"\s+", " ", (ocr_text or "")).strip()[:280]
        return JsonResponse({
            "ok": False,
            "error": "No recognizable resident fields found from the scanned ID.",
            "ocr_preview": preview,
        }, status=422)

    return JsonResponse({"ok": True, "data": extracted})

# CAPTAIN DASHBOARD
# CAPTAIN DASHBOARD
# CAPTAIN DASHBOARD

@login_required
@user_passes_test(is_captain)
def dashboard(request):

    today = timezone.localdate()

    residents = Resident.objects.all()

    total_residents = Resident.objects.count()
    total_households = Household.objects.count()

    male_residents = Resident.objects.filter(gender="Male").count()
    female_residents = Resident.objects.filter(gender="Female").count()

    alive = Resident.objects.filter(status="Alive").count()
    deceased = Resident.objects.filter(status="Deceased").count()
    moved = Resident.objects.filter(status="Moved").count()

    # Age calculations
    children = 0
    youth = 0
    adults = 0  
    seniors = 0
    for r in residents:
        age = r.age
        if age is None:
            continue
        if age <= 12:
            children += 1
        elif age <= 17:
            youth += 1
        elif age <= 59:
            adults += 1
        else:
            seniors += 1

    documents_issued = ServiceRequest.objects.count()

    # Complaint statistics
    total_complaints = Complaint.objects.count()

    pending_complaints = Complaint.objects.filter(
        status="Pending"
    ).count()

    investigating_complaints = Complaint.objects.filter(
        status="Under Investigation"
    ).count()

    resolved_complaints = Complaint.objects.filter(
        status="Resolved"
    ).count()

    # Financial statistics
    total_revenue = Payment.objects.aggregate(
    total=Sum("amount")
    )["total"] or 0

    # Recent service requests
    recent_requests = ServiceRequest.objects.select_related(
        "resident"
    ).order_by("-request_date")[:5]

    # Residents per purok
    purok_stats = Resident.objects.filter(
        household__isnull=False
    ).values(
        "household__purok"
    ).annotate(
        resident_count=Count("id")
    ).order_by("household__purok")

    context = {
        "total_residents": total_residents,
        "total_households": total_households,

        "male_residents": male_residents,
        "female_residents": female_residents,

        "children": children,
        "youth": youth,
        "adults": adults,
        "seniors": seniors,

        "alive": alive,
        "deceased": deceased,
        "moved": moved,

        "documents_issued": documents_issued,
        "total_revenue": total_revenue,

        "purok_stats": purok_stats,
        "recent_requests": recent_requests,

        "total_complaints": total_complaints,
        "pending_complaints": pending_complaints,
        "investigating_complaints": investigating_complaints,
        "resolved_complaints": resolved_complaints,
    }

    return render(request, "dashboard.html", context)

#ROLE-BASED REDIRECT
#ROLE-BASED REDIRECT
#ROLE-BASED REDIRECT
@login_required
def role_redirect(request):
    if request.user.groups.filter(name='Captain').exists():
        return redirect('captain_dashboard')

    elif request.user.groups.filter(name='Secretary').exists():
        return redirect('secretary_dashboard')

    elif request.user.groups.filter(name='Treasurer').exists():
        return redirect('treasurer_dashboard')

    elif request.user.groups.filter(name='Staff').exists():
        return redirect('staff_dashboard')

    elif is_resident(request.user):
        profile = get_user_profile(request.user)
        if profile and profile.is_verified and profile.resident:
            return redirect("portal_create_service_request")
        return redirect("portal_pending_verification")

    else:
        profile = get_user_profile(request.user)
        if profile:
            if profile.is_verified and profile.resident:
                return redirect("portal_create_service_request")
            return redirect("portal_pending_verification")
        return redirect('admin/')


def about_us(request):
    if request.user.is_authenticated:
        return render(request, "about_us.html")
    return render(request, "about_us_public.html")


def resident_register(request):
    if request.user.is_authenticated:
        return redirect("role_redirect")

    if request.method == "POST":
        form = ResidentPortalRegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.first_name = form.cleaned_data["first_name"].strip()
                user.last_name = form.cleaned_data["last_name"].strip()
                user.save()

                resident_group, _ = Group.objects.get_or_create(name="Resident")
                user.groups.clear()
                user.groups.add(resident_group)

                first_name = form.cleaned_data["first_name"].strip()
                last_name = form.cleaned_data["last_name"].strip()
                birth_date = form.cleaned_data["birthdate"]

                linked_resident = Resident.objects.filter(
                    first_name__iexact=first_name,
                    last_name__iexact=last_name,
                    birth_date=birth_date,
                    user_profile__isnull=True,
                ).first()

                profile = UserProfile.objects.create(
                    user=user,
                    resident=linked_resident,
                    first_name=first_name,
                    last_name=last_name,
                    birth_date=birth_date,
                    is_verified=False,
                    is_auto_matched=bool(linked_resident),
                )

            auth_login(request, user)

            if linked_resident:
                messages.info(
                    request,
                    "Registration successful. A matching resident record was found but still requires secretary verification.",
                )
            else:
                messages.info(request, "Registration successful. Your account is pending secretary verification.")
            return redirect("portal_pending_verification")
    else:
        form = ResidentPortalRegistrationForm()

    return render(request, "resident_register.html", {"form": form})


@login_required
def portal_pending_verification(request):
    if is_staff_user(request.user):
        return redirect("role_redirect")

    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, "Resident profile not found. Please register first.")
        return redirect("resident_register")

    if profile.is_verified and profile.resident:
        return redirect("portal_create_service_request")

    return render(request, "portal_pending_verification.html", {"profile": profile})


@login_required
@user_passes_test(is_secretary)
def pending_verifications(request):
    profiles = UserProfile.objects.filter(
        is_verified=False,
        user__is_active=True,
    ).select_related("user", "resident")

    return render(request, "pending_verifications.html", {"profiles": profiles})


@login_required
@user_passes_test(is_secretary)
def review_pending_verification(request, profile_id):
    profile = get_object_or_404(
        UserProfile.objects.select_related("user", "resident"),
        id=profile_id,
        is_verified=False,
        user__is_active=True,
    )

    suggested_residents = Resident.objects.filter(
        first_name__iexact=profile.first_name,
        last_name__iexact=profile.last_name,
        birth_date=profile.birth_date,
    ).select_related("household")

    available_residents = Resident.objects.filter(
        user_profile__isnull=True
    ).exclude(
        id__in=suggested_residents.values("id")
    ).order_by("last_name", "first_name")

    create_form = ResidentVerificationCreateForm(initial={
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "birth_date": profile.birth_date,
        "status": "Alive",
    })
    mismatch_warning = False
    mismatch_details = []
    selected_resident_id = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "approve":
            resident_id = request.POST.get("resident_id")
            resident = get_object_or_404(Resident, id=resident_id)
            selected_resident_id = resident.id
            if hasattr(resident, "user_profile") and resident.user_profile.user_id != profile.user_id:
                messages.error(request, "Selected resident record is already linked to another account.")
                return redirect("review_pending_verification", profile_id=profile.id)

            mismatch_details = []
            if (profile.first_name or "").strip().lower() != (resident.first_name or "").strip().lower():
                mismatch_details.append("First name does not match.")
            if (profile.last_name or "").strip().lower() != (resident.last_name or "").strip().lower():
                mismatch_details.append("Last name does not match.")
            if profile.birth_date != resident.birth_date:
                mismatch_details.append("Birthdate does not match.")

            mismatch_warning = len(mismatch_details) > 0
            confirm_override = request.POST.get("confirm_override") in ("1", "true", "True", "on", "yes")

            if mismatch_warning and not confirm_override:
                messages.warning(request, "Warning: The entered data does not match the selected resident.")
            else:
                before_data = snapshot_instance(profile)
                profile.resident = resident
                profile.is_verified = True
                profile.is_auto_matched = not mismatch_warning
                profile.save(update_fields=["resident", "is_verified", "is_auto_matched", "updated_at"])

                verification_mode = (
                    "Verified resident (manual override with mismatch)"
                    if mismatch_warning
                    else "Verified resident (auto match)"
                )

                log_audit_event(
                    action="UPDATE",
                    model_name="UserProfile",
                    description=(
                        f"{verification_mode}: Linked user {profile.user.username} "
                        f"to resident {resident.id}."
                    ),
                    user=request.user,
                    target_id=profile.id,
                    before_data=before_data,
                    after_data=snapshot_instance(profile),
                    request=request,
                )

                messages.success(request, f"Verified account for {profile.user.username}.")
                return redirect("pending_verifications")

        if action == "create":
            create_form = ResidentVerificationCreateForm(request.POST)
            if create_form.is_valid():
                resident = create_form.save()
                before_data = snapshot_instance(profile)
                profile.resident = resident
                profile.is_verified = True
                profile.is_auto_matched = False
                profile.save(update_fields=["resident", "is_verified", "is_auto_matched", "updated_at"])
                log_audit_event(
                    action="UPDATE",
                    model_name="UserProfile",
                    description=(
                        f"Verified resident (manual resident creation): Linked user "
                        f"{profile.user.username} to resident {resident.id}."
                    ),
                    user=request.user,
                    target_id=profile.id,
                    before_data=before_data,
                    after_data=snapshot_instance(profile),
                    request=request,
                )
                messages.success(request, f"Created new resident and verified {profile.user.username}.")
                return redirect("pending_verifications")
        elif action == "reject":
            before_data = snapshot_instance(profile)
            profile.user.is_active = False
            profile.user.save(update_fields=["is_active"])
            profile.resident = None
            profile.is_verified = False
            profile.is_auto_matched = False
            profile.save(update_fields=["resident", "is_verified", "is_auto_matched", "updated_at"])
            log_audit_event(
                action="UPDATE",
                model_name="UserProfile",
                description=f"Rejected resident verification for user {profile.user.username}.",
                user=request.user,
                target_id=profile.id,
                before_data=before_data,
                after_data=snapshot_instance(profile),
                request=request,
            )
            messages.warning(request, f"Rejected account {profile.user.username}.")
            return redirect("pending_verifications")

    return render(request, "review_pending_verification.html", {
        "profile": profile,
        "suggested_residents": suggested_residents,
        "available_residents": available_residents,
        "create_form": create_form,
        "mismatch_warning": mismatch_warning,
        "mismatch_details": mismatch_details,
        "selected_resident_id": selected_resident_id,
    })


@login_required
def portal_create_service_request(request):
    if not is_resident(request.user):
        return HttpResponseForbidden("Only resident accounts can access this page.")

    profile = get_user_profile(request.user)

    if not profile:
        messages.error(request, "Resident profile not found. Please register first.")
        return redirect("resident_register")

    if not profile.is_verified or not profile.resident:
        messages.error(request, "Your account is still pending verification.")
        return redirect("portal_pending_verification")

    return create_service_request(request, profile.resident.id)


@login_required
def portal_my_profile(request):
    if not is_resident(request.user):
        return HttpResponseForbidden("Only resident accounts can access this page.")

    profile = get_user_profile(request.user)
    if not profile or not profile.resident:
        messages.error(request, "Your resident profile is not linked yet.")
        return redirect("portal_pending_verification")
    if not profile.is_verified:
        messages.error(request, "Your account is still pending verification.")
        return redirect("portal_pending_verification")

    return redirect("resident_profile", resident_id=profile.resident_id)

#SECRETARY DASHBOARD
#SECRETARY DASHBOARD
#SECRETARY DASHBOARD
@group_required(is_secretary)
def secretary_dashboard(request):
    return render(request, 'secretary_dashboard.html')


#TREASURER DASHBOARD
#TREASURER DASHBOARD
#TREASURER DASHBOARD
@group_required(is_treasurer)
def treasurer_dashboard(request):

    today = timezone.localdate()
    month = today.month
    year = today.year

    # Paid clearances
    approved_requests = ServiceRequest.objects.filter(status="Approved")
    payments = Payment.objects.all()

    context = {
    "approved_requests": approved_requests,
    "payments": payments
}

    total_revenue = payments.aggregate(total=Sum("amount"))["total"] or 0

    today_collections = payments.filter(
    payment_date=today
    ).aggregate(total=Sum("amount"))["total"] or 0

    monthly_collections = payments.filter(
    payment_date__month=month,
    payment_date__year = year
    ).aggregate(total=Sum("amount"))["total"] or 0

    recent_payments = payments.order_by("-payment_date")[:5]

    # NEW: Monthly revenue chart data
    monthly_data = (
        Payment.objects
        .filter(payment_date__year=year)
        .annotate(month=ExtractMonth("payment_date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    months = [m["month"] for m in monthly_data]
    totals = [float(m["total"]) for m in monthly_data]



    return render(request, "treasurer_dashboard.html", {
        "total_revenue": total_revenue,
        "today_collections": today_collections,
        "monthly_collections": monthly_collections,
        "recent_payments": recent_payments,
        "months": months,
        "totals": totals
    })

#STAFF DASHBOARD
#STAFF DASHBOARD
#STAFF DASHBOARD
@group_required(is_staff_group_user)
def staff_dashboard(request):
    return render(request, 'staff_dashboard.html')

#RESIDENT LIST
#RESIDENT LIST
#RESIDENT LIST
@group_required(is_staff_user)
def resident_list(request):

    query = request.GET.get("q")
    gender = request.GET.get("gender")
    status = request.GET.get("status")

    residents = Resident.objects.all()

    if query:
        residents = residents.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)  |
            Q(middle_name__icontains=query) 
        )
    else:
        residents = Resident.objects.all()

    if gender:
        residents = residents.filter(gender=gender)

    if status:
        residents = residents.filter(status=status)

    context = {
        "residents": residents,
        "can_create_service_requests": can_create_service_requests(request.user),
    }

    return render(request, "resident_list.html", context)

#ADD RESIDENT
#ADD RESIDENT
#ADD RESIDENT
@group_required(is_secretary)
def add_resident(request):
    validation_errors = []

    if request.method == 'POST':
        form = ResidentForm(request.POST)

        if form.is_valid():
            resident = form.save()

            log_audit_event(
                action="CREATE",
                model_name="Resident",
                description=f"Added resident {resident.first_name} {resident.last_name}",
                user=request.user,
                target_id=resident.id,
                after_data=snapshot_instance(resident),
                request=request,
            )

            return redirect('resident_list')
        for field_name in form.errors.keys():
            if field_name == "__all__":
                continue
            label = form.fields.get(field_name).label if form.fields.get(field_name) else field_name
            if label and label not in validation_errors:
                validation_errors.append(label)
        messages.error(request, "Please complete all required fields before saving.")

    else:
        form = ResidentForm()

    return render(request, 'residents/add_resident.html', {
        'form': form,
        'validation_errors': validation_errors,
    })

#HOUSEHOLD
#HOUSEHOLD
#HOUSEHOLD
@group_required(is_staff_user)
def household_detail(request, pk):
    household = get_object_or_404(Household, pk=pk)

    members = household.members.all()

    total_members = members.count()
    voters = members.filter(voter_status=True).count()
    males = members.filter(gender="Male").count()
    females = members.filter(gender="Female").count()

    context = {
        "household": household,
        "members": members,
        "total_members": total_members,
        "voters": voters,
        "males": males,
        "females": females
    }

    return render(request, "household_detail.html", context)

#ADD RESIDENT TO HOUSEHOLD
#ADD RESIDENT TO HOUSEHOLD
#ADD RESIDENT TO HOUSEHOLD
@group_required(is_secretary)
def add_resident_to_household(request, household_id):
    household = get_object_or_404(Household, id=household_id)

    if request.method == "POST":
        form = ResidentForm(request.POST)
        if form.is_valid():
            resident = form.save(commit=False)
            resident.household = household
            resident.save()
            log_audit_event(
                action="UPDATE",
                model_name="Resident",
                description=f"Assigned resident {resident} to household {household.id}.",
                user=request.user,
                target_id=resident.id,
                after_data=snapshot_instance(resident),
                request=request,
            )
            return redirect("household_detail", pk=household.id)
    else:
        form = ResidentForm()

    return render(request, "residents/add_resident.html", {
        "form": form,
        "household": household
    })
#REMOVE FROM HOUSEHOLD
#REMOVE FROM HOUSEHOLD
#REMOVE FROM HOUSEHOLD
@group_required(is_secretary)
def remove_from_household(request, resident_id):
    resident = get_object_or_404(Resident, id=resident_id)

    before_data = snapshot_instance(resident)
    household = resident.household 

    resident.household = None
    resident.save()
    log_audit_event(
        action="UPDATE",
        model_name="Resident",
        description=f"Removed resident {resident} from household.",
        user=request.user,
        target_id=resident.id,
        before_data=before_data,
        after_data=snapshot_instance(resident),
        request=request,
    )

    if household:
        return redirect("household_detail", pk=household.id)

    return redirect("resident_list")

#HOUSEHOLD HEAD
#HOUSEHOLD HEAD
#HOUSEHOLD HEAD
@group_required(is_secretary)
def set_household_head(request, household_id, resident_id):
    household = get_object_or_404(Household, id=household_id)
    resident = get_object_or_404(Resident, id=resident_id)

    before_data = snapshot_instance(household)
    household.head = resident
    household.save()
    log_audit_event(
        action="UPDATE",
        model_name="Household",
        description=f"Set household {household.id} head to {resident}.",
        user=request.user,
        target_id=household.id,
        before_data=before_data,
        after_data=snapshot_instance(household),
        request=request,
    )

    return redirect("household_detail", pk=household.id)



#GENERATE CLEARANCE
#GENERATE CLEARANCE
#GENERATE CLEARANCE
@login_required
def create_service_request(request, resident_id):

    resident = get_object_or_404(Resident, id=resident_id)
    is_portal_resident_user = False

    if can_create_service_requests(request.user):
        pass
    elif not is_staff_user(request.user):
        if not is_resident(request.user):
            return HttpResponseForbidden("Only staff or resident accounts can create service requests.")
        profile = get_user_profile(request.user)
        if not profile or not profile.is_verified or not profile.resident:
            messages.error(request, "Only verified resident portal accounts can create service requests.")
            return redirect("portal_pending_verification")
        if profile.resident_id != resident.id:
            messages.error(request, "You can only create requests for your own linked resident record.")
            return redirect("portal_create_service_request")
        is_portal_resident_user = True
    else:
        return HttpResponseForbidden("Only the Secretary, Staff, or the verified resident can create service requests.")

    service_types = ServiceType.objects.all()
    service_purposes = RequestPurpose.objects.filter(is_active=True)

    def render_request_form():
        return render(request, "service_request_form.html", {
            "resident": resident,
            "service_types": service_types,
            "service_purposes": service_purposes,
            "posted_data": request.POST if request.method == "POST" else None,
            "is_portal_resident_user": is_portal_resident_user,
        })

    if request.method == "POST":

        service_type_id = request.POST.get("service_type")
        purpose_option_id = request.POST.get("purpose_for")
        purpose_other = (request.POST.get("purpose_other") or "").strip()

        if not service_type_id:
            messages.error(request, "Please select a service type.")
            return render_request_form()

        service_type = get_object_or_404(ServiceType, id=service_type_id)
        service_name = service_type.name.lower().strip()
        normalized_service = re.sub(r"[^a-z0-9]+", " ", service_name).strip()
        is_indigency = normalized_service == "indigency"
        is_barangay_id = normalized_service == "barangay id"
        is_qcid = normalized_service in ("qcid", "qc id")
        is_general_service_request = normalized_service == "service request"

        requires_purpose = is_indigency or is_general_service_request
        requires_emergency = is_barangay_id
        requires_residency = is_qcid

        purpose_option = None
        purpose_text = None
        if requires_purpose:
            if not purpose_option_id:
                messages.error(request, "Please select a purpose.")
                return render_request_form()
            purpose_option = get_object_or_404(RequestPurpose, id=purpose_option_id, is_active=True)

            if purpose_option.requires_details and not purpose_other:
                messages.error(request, "Please specify the purpose details.")
                return render_request_form()
            purpose_text = purpose_other if purpose_option.requires_details else purpose_option.name

        emergency_contact_name = (request.POST.get("emergency_contact_name") or "").strip() or None
        emergency_contact_address = (request.POST.get("emergency_contact_address") or "").strip() or None
        emergency_contact_number = (request.POST.get("emergency_contact_number") or "").strip() or None
        residency_since = (request.POST.get("residency_since") or None)

        if requires_emergency:
            if not emergency_contact_name or not emergency_contact_address or not emergency_contact_number:
                messages.error(request, "Please complete all emergency contact fields for Barangay ID.")
                return render_request_form()

        if requires_residency and not residency_since:
            messages.error(request, "Please provide residency date for QCID.")
            return render_request_form()

        service = ServiceRequest.objects.create(
            resident=resident,
            service_type=service_type,
            purpose_option=purpose_option,
            purpose=purpose_text,
            purpose_for=(purpose_option.name if purpose_option else None),
            purpose_other=(purpose_other or None) if purpose_option else None,
            emergency_contact_name=emergency_contact_name if requires_emergency else None,
            emergency_contact_address=emergency_contact_address if requires_emergency else None,
            emergency_contact_number=emergency_contact_number if requires_emergency else None,
            residency_since=residency_since if requires_residency else None,
            status="Pending",
            created_by=request.user,
        )
        
        #Payment.objects.create(
    #service_request=service,
    #amount=service_type.fee,
    #collected_by=request.user
#)
        log_audit_event(
         action="CREATE",
         model_name="ServiceRequest",
         description=f"Created {service_type} request for {resident}",
         user=request.user,
         target_id=service.id,
         after_data=snapshot_instance(service),
         request=request,
        )

        # Generate clearance number
        year = service.request_date.year
        service.clearance_number = f"{year}-{service.id:04d}"
        service.save()

        if is_portal_resident_user:
            messages.success(request, "Your service request was submitted successfully.")
            return redirect("portal_my_profile")

        return redirect("generate_document", request_id=service.id)

    return render_request_form()

#UPDATE SERVICE REQUEST STATUS
#UPDATE SERVICE REQUEST STATUS
#UPDATE SERVICE REQUEST STATUS
@group_required(is_staff_user)
def update_service_request_status(request, request_id):

    service_request = get_object_or_404(ServiceRequest, id=request_id)

    if request.method == "POST":

        new_status = request.POST.get("status")
        before_data = snapshot_instance(service_request)

        # prevent release without payment
        if new_status == "Released" and not hasattr(service_request, "payment"):
            messages.error(request, "Payment required before releasing document.")
            return redirect(request.META.get("HTTP_REFERER"))

        if new_status in dict(ServiceRequest.STATUS_CHOICES):
            service_request.status = new_status
            service_request.save()
            log_audit_event(
                action="UPDATE",
                model_name="ServiceRequest",
                description=f"Updated request {service_request.clearance_number} to {new_status}.",
                user=request.user,
                target_id=service_request.id,
                before_data=before_data,
                after_data=snapshot_instance(service_request),
                request=request,
            )

    return redirect(request.META.get("HTTP_REFERER"))

#RESIDENT PROFILE
#RESIDENT PROFILE
#RESIDENT PROFILE
@login_required
def resident_profile(request, resident_id):
    resident = get_object_or_404(Resident, id=resident_id)
    is_portal_resident_user = False
    can_create_requests = False
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident or profile.resident_id != resident.id:
            return HttpResponseForbidden("You can only view your own resident profile.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        services = ServiceRequest.objects.filter(resident=profile.resident)
        is_portal_resident_user = True
        can_create_requests = True
    elif is_staff_user(request.user):
        services = ServiceRequest.objects.filter(resident=resident)
        can_create_requests = can_create_service_requests(request.user)
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")
    
    context = {
    "resident": resident,
    "services": services,
    "is_portal_resident_user": is_portal_resident_user,
    "can_create_service_requests": can_create_requests,
}
    return render(request, "resident_profile.html", context)


#EDIT RESIDENT
#EDIT RESIDENT
#EDIT RESIDENT
@group_required(is_secretary)
def edit_resident(request, resident_id):

    resident = get_object_or_404(Resident, id=resident_id)

    if request.method == "POST":
        before_data = snapshot_instance(resident)
        form = ResidentForm(request.POST, instance=resident)
        if form.is_valid():
            updated_resident = form.save()
            log_audit_event(
                action="UPDATE",
                model_name="Resident",
                description=f"Updated resident {resident.first_name} {resident.last_name}",
                user=request.user,
                target_id=resident.id,
                before_data=before_data,
                after_data=snapshot_instance(updated_resident),
                request=request,
            )
            
            return redirect("resident_profile", resident_id=resident.id)

    else:
        form = ResidentForm(instance=resident)

    return render(request, "edit_resident.html", {  
    "form": form,
    "resident": resident
})

#PAYMENT LIST
#PAYMENT LIST
#PAYMENT LIST
@group_required(is_treasurer)
def payment_list(request):

    # requests waiting for payment
    approved_requests = ServiceRequest.objects.filter(status="Approved")

    # already paid
    payments = Payment.objects.all()

    return render(request, "payment_list.html", {
        "approved_requests": approved_requests,
        "payments": payments
    })

#RECORS PAYMENT
#RECORD PAYMENT
@group_required(is_treasurer)
def record_payment(request, request_id):
    if request.method != "POST":
        return redirect("payment_list")

    service_request = get_object_or_404(ServiceRequest, id=request_id)

    if service_request.status != "Approved":
        messages.error(request, "Only approved requests can be paid at the cashier.")
        return redirect("payment_list")

    # prevent duplicate payments
    if Payment.objects.filter(service_request=service_request).exists():
        messages.warning(request, "Payment already exists for this request.")
        return redirect("payment_list")

    before_status = snapshot_instance(service_request)
    payment = Payment.objects.create(
        service_request=service_request,
        amount=service_request.fee,
        collected_by=request.user
    )
    log_audit_event(
        action="CREATE",
        model_name="Payment",
        description=f"Payment recorded for {service_request.resident}.",
        user=request.user,
        target_id=payment.id,
        after_data=snapshot_instance(payment),
        request=request,
    )

    service_request.status = "Released"
    service_request.save()
    log_audit_event(
        action="UPDATE",
        model_name="ServiceRequest",
        description=f"Request {service_request.document_number} released after payment.",
        user=request.user,
        target_id=service_request.id,
        before_data=before_status,
        after_data=snapshot_instance(service_request),
        request=request,
    )

    return redirect("generate_document", request_id=service_request.id)

#ADD HOUSEHOLD
#ADD HOUSEHOLD
#ADD HOUSEHOLD
@login_required
@user_passes_test(is_secretary)
def add_household(request):

    if request.method == "POST":
        form = HouseholdForm(request.POST)

        if form.is_valid():
            household = form.save()
            log_audit_event(
                action="CREATE",
                model_name="Household",
                description=f"Added household {household.id}.",
                user=request.user,
                target_id=household.id,
                after_data=snapshot_instance(household),
                request=request,
            )
            return redirect("secretary_dashboard")

    else:
        form = HouseholdForm()

    return render(request, "add_household.html", {"form": form})

#HOUSEHOLD LIST
#HOUSEHOLD LIST
# HOUSEHOLD LIST
@group_required(is_staff_user)
def household_list(request):

    households = Household.objects.all().order_by("purok", "house_number")

    purok = request.GET.get("purok")
    search = request.GET.get("q")

    if purok:
        households = households.filter(purok=purok)

    if search:
        households = households.filter(
            street__icontains=search
        )

    context = {
        "households": households
    }

    return render(request, "household_list.html", context)

#COMPLAINT LIST     
#COMPLAINT LIST
#COMPLAINT LIST
@login_required
def complaint_list(request):
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident:
            return HttpResponseForbidden("Resident profile not linked.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        complaints = Complaint.objects.filter(
            resident=profile.resident
        ).order_by("-date_filed")
    elif is_staff_user(request.user):
        complaints = Complaint.objects.all().order_by("-date_filed")
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")

    return render(request, "complaint_list.html", {
        "complaints": complaints
    })

#FILE COMPLAINT
#FILE COMPLAINT
#FILE COMPLAINT
@login_required
def file_complaint(request):
    resident_profile = None
    is_resident_user = is_resident(request.user)
    if is_resident_user:
        resident_profile = get_user_profile(request.user)
        if not resident_profile or not resident_profile.resident:
            messages.error(request, "Your resident profile is not linked yet.")
            return redirect("portal_pending_verification")
        if not resident_profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
    elif not is_staff_user(request.user):
        return HttpResponseForbidden("You do not have permission to access this page.")

    if request.method == "POST":
        if is_resident_user:
            post_data = request.POST.copy()
            post_data["resident"] = str(resident_profile.resident_id)
            form = ComplaintForm(post_data)
        else:
            form = ComplaintForm(request.POST)

        if form.is_valid():
            complaint = form.save(commit=False)
            if is_resident_user:
                complaint.resident = resident_profile.resident
            complaint.filed_by = request.user
            complaint.save()

            log_audit_event(
                action="CREATE",
                model_name="Complaint",
                description=f"Complaint filed: {complaint.title}",
                user=request.user,
                target_id=complaint.id,
                after_data=snapshot_instance(complaint),
                request=request,
            )
            return redirect("complaint_list")

    else:
        form = ComplaintForm()

    if is_resident_user:
        form.fields["resident"].widget = form.fields["resident"].hidden_widget()

    return render(request, "file_complaint.html", {
        "form": form,
        "is_resident_user": is_resident_user,
        "resident_profile": resident_profile,
    })

#COMPLAINT DETAIL
#COMPLAINT DETAIL
#COMPLAINT DETAIL
@login_required
def complaint_detail(request, complaint_id):

    complaint = get_object_or_404(Complaint, id=complaint_id)
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident or complaint.resident_id != profile.resident_id:
            return HttpResponseForbidden("You can only view your own complaints.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        can_update_status = False
    elif is_staff_user(request.user):
        can_update_status = True
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")

    return render(request, "complaint_detail.html", {
        "complaint": complaint,
        "can_update_status": can_update_status,
    })

#UPDATE COMPLAINT STATUS
#UPDATE COMPLAINT STATUS
#UPDATE COMPLAINT STATUS
@group_required(is_staff_user)
def update_complaint_status(request, complaint_id):

    complaint = get_object_or_404(Complaint, id=complaint_id)

    if request.method == "POST":
        before_data = snapshot_instance(complaint)
        new_status = request.POST.get("status")
        complaint.status = new_status
        complaint.save()
        log_audit_event(
            action="UPDATE",
            model_name="Complaint",
            description=f"Complaint '{complaint.title}' updated to {new_status}",
            user=request.user,
            target_id=complaint.id,
            before_data=before_data,
            after_data=snapshot_instance(complaint),
            request=request,
        )

    return redirect("complaint_detail", complaint_id=complaint.id)

#EXPORT RESDIENTS CSV
#EXPORT RESDIENTS CSV
#EXPORT RESIDENTS CSV
@login_required
@user_passes_test(is_captain)
def export_residents_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="residents_report.csv"'

    writer = csv.writer(response)

    # Header row
    writer.writerow([
        "First Name",
        "Last Name",
        "Gender",
        "Birth Date",
        "Civil Status",
        "Voter Status",
        "Resident Status",
        "Purok"
    ])

    residents = Resident.objects.select_related("household").all()

    for resident in residents:

        purok = resident.household.purok if resident.household else "N/A"

        writer.writerow([
            resident.first_name,
            resident.last_name,
            resident.gender,
            resident.birth_date,
            resident.civil_status,
            resident.voter_status,
            resident.status,
            purok
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Resident",
        description=f"Exported residents CSV ({residents.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT PAYMENTS CSV
#EXPORT PAYMENTS CSV
#EXPORT PAYMENTS CSV
@group_required(is_staff_user)
def export_payments_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="payments_report.csv"'

    writer = csv.writer(response)

    # Header
    writer.writerow([
        "Receipt Number",
        "Resident",
        "Service",
        "Amount",
        "Payment Date",
        "Collected By"
    ])

    payments = Payment.objects.select_related(
        "service_request__resident"
    ).all()

    for payment in payments:

        writer.writerow([
            payment.receipt_number,
            payment.service_request.resident,
            payment.service_request.service_type,
            payment.amount,
            payment.payment_date,
            payment.collected_by
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Payment",
        description=f"Exported payments CSV ({payments.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT HOUSEHOLDS CSV
#EXPORT HOUSEHOLDS CSV
#EXPORT HOUSEHOLDS CSV
@login_required
@user_passes_test(is_captain)
def export_households_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="households_report.csv"'

    writer = csv.writer(response)

    writer.writerow([
        "Household ID",
        "Household Head",
        "Purok",
        "Total Members"
    ])

    households = Household.objects.all()

    for household in households:

        head = household.head if household.head else "None"
        members = household.members.count()

        writer.writerow([
            household.id,
            head,
            household.purok,
            members
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Household",
        description=f"Exported households CSV ({households.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT COMPLAINTS CSV
#EXPORT COMPLAINTS CSV
#EXPORt COMPLAINTS CSV
@login_required
@user_passes_test(is_captain)
def export_complaints_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="complaints_report.csv"'

    writer = csv.writer(response)

    writer.writerow([
        "Complaint Title",
        "Resident",
        "Description",
        "Status",
        "Date Filed"
    ])

    complaints = Complaint.objects.select_related("resident").all()

    for complaint in complaints:

        writer.writerow([
            complaint.title,
            complaint.resident,
            complaint.description,
            complaint.status,
            complaint.date_filed
        ])
    log_audit_event(
        action="EXPORT",
        model_name="Complaint",
        description=f"Exported complaints CSV ({complaints.count()} records).",
        user=request.user,
        request=request,
    )

    return response

#EXPORT BARANGAY SUMMARY CSV
#EXPORT BARANGAY SUMMARY CSV
#EXPORT BARANGAY SUMMARY CSV
@login_required
@user_passes_test(is_captain)
def export_barangay_summary_csv(request):

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="barangay_summary_report.csv"'

    writer = csv.writer(response)

    writer.writerow(["Barangay Summary Report"])
    writer.writerow([])

    total_residents = Resident.objects.count()
    total_households = Household.objects.count()
    total_complaints = Complaint.objects.count()
    documents_issued = ServiceRequest.objects.count()

    total_revenue = Payment.objects.aggregate(
    total=Sum("amount")
    )["total"] or 0

    writer.writerow(["Total Residents", total_residents])
    writer.writerow(["Total Households", total_households])
    writer.writerow(["Total Complaints", total_complaints])
    writer.writerow(["Documents Issued", documents_issued])
    writer.writerow(["Total Revenue", total_revenue])
    log_audit_event(
        action="EXPORT",
        model_name="BarangaySummary",
        description="Exported barangay summary CSV report.",
        user=request.user,
        request=request,
    )

    return response



#Generate_Document
#Generate_Document
#Generate_Document

@group_required(is_staff_user)
def generate_document(request, request_id):

    service = get_object_or_404(ServiceRequest, id=request_id)

    resident = service.resident
    address = "-"
    if resident.household:
        address = f"{resident.household.house_number} {resident.household.street}"

    # Decide which template to load
    service_name = service.service_type.name.lower()
    if "clearance" in service_name:
        template = "clearance_print.html"

    elif "residency" in service_name:
        template = "residency_print.html"

    elif "indigency" in service_name:
        template = "indigency_print.html"

    elif "qcid" in service_name or "qc id" in service_name:
        template = "qcid_print.html"

    elif "barangay id" in service_name:
        template = "barangay_id_print.html"

    else:
        template = "clearance_print.html"

    context = {
        "service": service,
        "resident": resident,
        "address": address,
        "today": timezone.localdate(),
    }
    log_audit_event(
        action="PRINT",
        model_name="ServiceRequest",
        description=f"Generated document for request {service.document_number}.",
        user=request.user,
        target_id=service.id,
        request=request,
    )

    return render(request, template, context)

# SERVICE REQUEST LIST
# SERVICE REQUEST LIST
# SERVICE REQUEST LIST
@login_required
def service_requests(request):
    if is_resident(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.resident:
            return HttpResponseForbidden("Resident profile not linked.")
        if not profile.is_verified:
            messages.error(request, "Your account is still pending verification.")
            return redirect("portal_pending_verification")
        requests = ServiceRequest.objects.select_related(
            "resident"
        ).filter(
            resident=profile.resident
        ).order_by("-request_date")
    elif is_staff_user(request.user):
        requests = ServiceRequest.objects.select_related(
            "resident"
        ).order_by("-request_date")
    else:
        return HttpResponseForbidden("You do not have permission to access this page.")

    return render(request, "service_requests.html", {
        "requests": requests
    })

@login_required
@user_passes_test(is_captain)
def audit_logs(request):
    logs = AuditLog.objects.select_related("user").all()
    users = User.objects.filter(is_active=True).order_by("username")
    models = AuditLog.objects.values_list("model_name", flat=True).distinct().order_by("model_name")

    action = request.GET.get("action", "").strip()
    model_name = request.GET.get("model_name", "").strip()
    user_id = request.GET.get("user_id", "").strip()
    q = request.GET.get("q", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    if action:
        logs = logs.filter(action=action)
    if model_name:
        logs = logs.filter(model_name=model_name)
    if user_id:
        logs = logs.filter(user_id=user_id)
    if start_date:
        logs = logs.filter(timestamp__date__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__date__lte=end_date)
    if q:
        logs = logs.filter(
            Q(description__icontains=q)
            | Q(target_id__icontains=q)
            | Q(user__username__icontains=q)
        )

    return render(request, "audit_logs.html", {
        "logs": logs,
        "users": users,
        "models": models,
        "actions": AuditLog.ACTION_CHOICES,
        "filters": {
            "action": action,
            "model_name": model_name,
            "user_id": user_id,
            "q": q,
            "start_date": start_date,
            "end_date": end_date,
        },
    })
