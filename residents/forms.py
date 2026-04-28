from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import RegexValidator, validate_email
from django.core.exceptions import ValidationError

from .models import Complaint, Household, Resident, ServiceRequest


EMAIL_MESSAGE = "Email must be in valid format (example@domain.com)."
PHONE_MESSAGE = "Mobile number must contain only digits."
REQUIRED_MESSAGE = "This field is required."
PASSWORD_MESSAGE = (
    "Password must be at least 8 characters and include uppercase, lowercase, a number, and a symbol."
)

phone_digits_validator = RegexValidator(r"^\d+$", PHONE_MESSAGE)


def clean_required_text(value, *, field_label="This field", max_length=None):
    cleaned = (value or "").strip()
    if not cleaned:
        raise forms.ValidationError(REQUIRED_MESSAGE)
    if max_length is not None and len(cleaned) > max_length:
        raise forms.ValidationError(f"{field_label} must be {max_length} characters or fewer.")
    return cleaned


def clean_optional_text(value, *, field_label="This field", max_length=None):
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if max_length is not None and len(cleaned) > max_length:
        raise forms.ValidationError(f"{field_label} must be {max_length} characters or fewer.")
    return cleaned


def clean_email_value(value, *, required=False):
    cleaned = (value or "").strip().lower()
    if not cleaned:
        if required:
            raise forms.ValidationError(REQUIRED_MESSAGE)
        return ""
    try:
        validate_email(cleaned)
    except ValidationError as exc:
        raise forms.ValidationError(EMAIL_MESSAGE) from exc
    return cleaned


def clean_phone_value(value, *, required=False, min_length=7, max_length=15):
    raw = (value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        if required:
            raise forms.ValidationError(REQUIRED_MESSAGE)
        return ""
    if any(not ch.isdigit() and not ch.isspace() and ch not in "+-()"
           for ch in raw):
        raise forms.ValidationError(PHONE_MESSAGE)
    phone_digits_validator(digits)
    if len(digits) < min_length or len(digits) > max_length:
        raise forms.ValidationError(f"Mobile number must be {min_length} to {max_length} digits.")
    return digits


def validate_strong_password(value):
    if not value:
        raise forms.ValidationError(REQUIRED_MESSAGE)
    if (
        len(value) < 8
        or not any(ch.islower() for ch in value)
        or not any(ch.isupper() for ch in value)
        or not any(ch.isdigit() for ch in value)
        or not any(not ch.isalnum() for ch in value)
    ):
        raise forms.ValidationError(PASSWORD_MESSAGE)
    return value


class ResidentForm(forms.ModelForm):
    CIVIL_STATUS_CHOICES = [
        ("", "---------"),
        ("Single", "Single"),
        ("Married", "Married"),
        ("Widowed", "Widowed"),
        ("Separated", "Separated"),
        ("Divorced", "Divorced"),
    ]
    civil_status = forms.ChoiceField(choices=CIVIL_STATUS_CHOICES)
    permanent_address = forms.TypedChoiceField(
        choices=(
            ("", "Select an option"),
            ("True", "Yes"),
            ("False", "No"),
        ),
        coerce=lambda value: None if value == "" else value == "True",
        empty_value=None,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].required = False
        if not self.instance or not self.instance.pk:
            self.fields["status"].initial = "Alive"
        self.fields["first_name"].widget.attrs.setdefault("placeholder", "Enter first name")
        self.fields["middle_name"].widget.attrs.setdefault("placeholder", "Enter middle name")
        self.fields["last_name"].widget.attrs.setdefault("placeholder", "Enter last name")
        self.fields["suffix"].widget.attrs.setdefault("placeholder", "Jr., Sr., III")
        self.fields["place_of_birth"].widget.attrs.setdefault("placeholder", "City or municipality of birth")
        self.fields["nationality"].widget.attrs.setdefault("placeholder", "e.g. Filipino")
        self.fields["religion"].widget.attrs.setdefault("placeholder", "Enter religion")
        self.fields["occupation"].widget.attrs.setdefault("placeholder", "Enter occupation")
        self.fields["contact_number"].widget.attrs.update({
            "placeholder": "09XX XXX XXXX",
            "inputmode": "numeric",
            "maxlength": "15",
            "data-validation-label": "Mobile number",
        })
        self.fields["email"].widget.attrs.update({
            "placeholder": "name@example.com",
            "type": "email",
            "autocomplete": "email",
            "data-validation-label": "Email address",
        })
        self.fields["precinct"].widget.attrs.setdefault("placeholder", "Enter precinct number")
        self.fields["address_house_number"].widget.attrs.setdefault("placeholder", "House number")
        self.fields["address_street"].widget.attrs.setdefault("placeholder", "Street")
        self.fields["address_barangay"].widget.attrs.setdefault("placeholder", "Barangay")
        self.fields["address_city"].widget.attrs.setdefault("placeholder", "Municipality/City")
        self.fields["address_province"].widget.attrs.setdefault("placeholder", "Province")
        self.fields["birth_date"].widget.attrs.update({
            "max": date.today().isoformat(),
        })
        self.fields["household"].queryset = Household.objects.order_by("house_number", "street")
        if self.instance and self.instance.pk:
            self.fields["permanent_address"].initial = self.instance.permanent_address
        else:
            self.fields["permanent_address"].initial = None
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} bmis-checkbox".strip()
            elif isinstance(widget, forms.Select):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} bmis-select".strip()
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} bmis-input".strip()
            if hasattr(field, "max_length") and field.max_length:
                widget.attrs.setdefault("maxlength", str(field.max_length))

    def clean_first_name(self):
        return clean_required_text(self.cleaned_data.get("first_name"), field_label="First name", max_length=100)

    def clean_middle_name(self):
        return clean_optional_text(self.cleaned_data.get("middle_name"), field_label="Middle name", max_length=100)

    def clean_last_name(self):
        return clean_required_text(self.cleaned_data.get("last_name"), field_label="Last name", max_length=100)

    def clean_suffix(self):
        return clean_optional_text(self.cleaned_data.get("suffix"), field_label="Suffix", max_length=20)

    def clean_place_of_birth(self):
        return clean_optional_text(self.cleaned_data.get("place_of_birth"), field_label="Place of birth", max_length=150)

    def clean_nationality(self):
        return clean_optional_text(self.cleaned_data.get("nationality"), field_label="Nationality", max_length=100)

    def clean_religion(self):
        return clean_optional_text(self.cleaned_data.get("religion"), field_label="Religion", max_length=100)

    def clean_occupation(self):
        return clean_optional_text(self.cleaned_data.get("occupation"), field_label="Occupation", max_length=120)

    def clean_contact_number(self):
        return clean_phone_value(self.cleaned_data.get("contact_number"), required=False)

    def clean_email(self):
        return clean_email_value(self.cleaned_data.get("email"), required=False)

    def clean_precinct(self):
        return clean_optional_text(self.cleaned_data.get("precinct"), field_label="Precinct number", max_length=50)

    def clean_address_house_number(self):
        return clean_optional_text(self.cleaned_data.get("address_house_number"), field_label="House number", max_length=50)

    def clean_address_street(self):
        return clean_optional_text(self.cleaned_data.get("address_street"), field_label="Street", max_length=150)

    def clean_address_barangay(self):
        return clean_optional_text(self.cleaned_data.get("address_barangay"), field_label="Barangay", max_length=100)

    def clean_address_city(self):
        return clean_optional_text(self.cleaned_data.get("address_city"), field_label="Municipality/City", max_length=100)

    def clean_address_province(self):
        return clean_optional_text(self.cleaned_data.get("address_province"), field_label="Province", max_length=100)

    class Meta:
        model = Resident
        widgets = {
            "birth_date": forms.DateInput(attrs={
                "type": "date"
            })
        }
        fields = [
            'first_name',
            'middle_name',
            'last_name',
            'suffix',
            'birth_date',
            'place_of_birth',
            'gender',
            'civil_status',
            'nationality',
            'religion',
            'occupation',
            'educational_attainment',
            'pwd',
            'indigenous',
            'solo_parent',
            'voter_status',
            'status',
            'contact_number',
            'email',
            'permanent_address',
            'address_house_number',
            'address_street',
            'address_barangay',
            'address_city',
            'address_province',
            'precinct',
            'household',

        ]

    def clean_status(self):
        status = self.cleaned_data.get("status")
        if status:
            return status
        if self.instance and self.instance.pk:
            return self.instance.status
        return "Alive"

    def clean(self):
        cleaned_data = super().clean()
        permanent_address = cleaned_data.get("permanent_address")
        voter_status = cleaned_data.get("voter_status")

        if permanent_address is None:
            self.add_error("permanent_address", "Select Yes or No.")

        for field_name in [
            "address_house_number",
            "address_street",
            "address_barangay",
            "address_city",
            "address_province",
        ]:
            value = cleaned_data.get(field_name)
            if isinstance(value, str):
                cleaned_data[field_name] = value.strip()

        if permanent_address:
            cleaned_data["address_barangay"] = "Gulod"
            cleaned_data["address_city"] = "Quezon City"
            cleaned_data["address_province"] = "Metro Manila"
        elif permanent_address is False:
            for field_name in [
                "address_house_number",
                "address_street",
                "address_barangay",
                "address_city",
                "address_province",
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, "This field is required.")

        if not voter_status:
            cleaned_data["precinct"] = ""

        return cleaned_data


class ResidentPortalRegistrationForm(UserCreationForm):
    CIVIL_STATUS_CHOICES = ResidentForm.CIVIL_STATUS_CHOICES
    REGISTRATION_STATUS_CHOICES = [
        choice for choice in Resident.STATUS_CHOICES if choice[0] not in {"Deceased", "Moved"}
    ]

    first_name = forms.CharField(max_length=100)
    middle_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=100)
    suffix = forms.CharField(max_length=20, required=False)
    birthdate = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    place_of_birth = forms.CharField(max_length=150, required=False)
    gender = forms.ChoiceField(choices=Resident.GENDER_CHOICES)
    civil_status = forms.ChoiceField(choices=CIVIL_STATUS_CHOICES)
    nationality = forms.CharField(max_length=100, required=False)
    religion = forms.CharField(max_length=100, required=False)
    occupation = forms.CharField(max_length=120, required=False)
    educational_attainment = forms.ChoiceField(
        choices=Resident.EDUCATIONAL_ATTAINMENT_CHOICES,
        required=False,
    )
    contact_number = forms.CharField(max_length=15, required=False)
    email = forms.EmailField(required=False)
    precinct = forms.CharField(max_length=50, required=False)
    permanent_address = forms.TypedChoiceField(
        choices=(
            ("", "Select an option"),
            ("True", "Yes"),
            ("False", "No"),
        ),
        coerce=lambda value: None if value == "" else value == "True",
        empty_value=None,
    )
    address_house_number = forms.CharField(max_length=50, required=False)
    address_street = forms.CharField(max_length=150, required=False)
    address_barangay = forms.CharField(max_length=100, required=False)
    address_city = forms.CharField(max_length=100, required=False)
    address_province = forms.CharField(max_length=100, required=False)
    pwd = forms.BooleanField(required=False)
    indigenous = forms.BooleanField(required=False)
    solo_parent = forms.BooleanField(required=False)
    voter_status = forms.BooleanField(required=False)
    status = forms.ChoiceField(choices=REGISTRATION_STATUS_CHOICES, required=False, initial="Alive")
    address = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.HiddenInput(),
    )
    valid_id_image = forms.ImageField()
    consent_agreement = forms.BooleanField(
        required=True,
        error_messages={"required": "You must agree to the data privacy consent before registering."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Use 150 characters or fewer. Letters, numbers, and @/./+/-/_ only."
        self.fields["password1"].help_text = "Use at least 8 characters with a mix of letters, numbers, and symbols."
        self.fields["password2"].help_text = "Re-enter the same password to confirm."
        self.fields["civil_status"].initial = "Single"
        self.fields["nationality"].initial = "Filipino"
        self.fields["status"].initial = "Alive"
        self.fields["username"].widget.attrs.setdefault("autocomplete", "username")
        self.fields["username"].widget.attrs.setdefault("placeholder", "Choose a username")
        self.fields["first_name"].widget.attrs.setdefault("autocomplete", "given-name")
        self.fields["first_name"].widget.attrs.setdefault("placeholder", "Enter first name")
        self.fields["middle_name"].widget.attrs.setdefault("autocomplete", "additional-name")
        self.fields["last_name"].widget.attrs.setdefault("autocomplete", "family-name")
        self.fields["last_name"].widget.attrs.setdefault("placeholder", "Enter last name")
        self.fields["birthdate"].widget.attrs.setdefault("autocomplete", "bday")
        self.fields["email"].widget.attrs.setdefault("autocomplete", "email")
        self.fields["password1"].widget.attrs.setdefault("autocomplete", "new-password")
        self.fields["password2"].widget.attrs.setdefault("autocomplete", "new-password")
        self.fields["middle_name"].widget.attrs.setdefault("placeholder", "Enter middle name")
        self.fields["suffix"].widget.attrs.setdefault("placeholder", "Jr., Sr., III")
        self.fields["place_of_birth"].widget.attrs.setdefault("placeholder", "City or municipality of birth")
        self.fields["nationality"].widget.attrs.setdefault("placeholder", "e.g. Filipino")
        self.fields["religion"].widget.attrs.setdefault("placeholder", "Enter religion")
        self.fields["occupation"].widget.attrs.setdefault("placeholder", "Enter occupation")
        self.fields["contact_number"].widget.attrs.update({
            "placeholder": "09XX XXX XXXX",
            "inputmode": "numeric",
            "maxlength": "15",
        })
        self.fields["email"].widget.attrs.update({
            "placeholder": "name@example.com",
            "type": "email",
        })
        self.fields["precinct"].widget.attrs.setdefault("placeholder", "Enter precinct number")
        self.fields["address_house_number"].widget.attrs.setdefault("placeholder", "House number")
        self.fields["address_street"].widget.attrs.setdefault("placeholder", "Street")
        self.fields["address_barangay"].widget.attrs.setdefault("placeholder", "Barangay")
        self.fields["address_city"].widget.attrs.setdefault("placeholder", "Municipality/City")
        self.fields["address_province"].widget.attrs.setdefault("placeholder", "Province")
        self.fields["birthdate"].widget.attrs.setdefault("max", date.today().isoformat())
        self.fields["contact_number"].widget.attrs.setdefault("autocomplete", "tel")
        self.fields["valid_id_image"].widget.attrs.setdefault("accept", "image/*")
        self.fields["consent_agreement"].label = "I agree to the collection and processing of my personal data for resident registration."
        for field in self.fields.values():
            if hasattr(field, "max_length") and field.max_length:
                field.widget.attrs.setdefault("maxlength", str(field.max_length))

    def clean_username(self):
        return clean_required_text(self.cleaned_data.get("username"), field_label="Username", max_length=150)

    def clean_first_name(self):
        return clean_required_text(self.cleaned_data.get("first_name"), field_label="First name", max_length=100)

    def clean_middle_name(self):
        return clean_optional_text(self.cleaned_data.get("middle_name"), field_label="Middle name", max_length=100)

    def clean_last_name(self):
        return clean_required_text(self.cleaned_data.get("last_name"), field_label="Last name", max_length=100)

    def clean_suffix(self):
        return clean_optional_text(self.cleaned_data.get("suffix"), field_label="Suffix", max_length=20)

    def clean_place_of_birth(self):
        return clean_optional_text(self.cleaned_data.get("place_of_birth"), field_label="Place of birth", max_length=150)

    def clean_nationality(self):
        return clean_optional_text(self.cleaned_data.get("nationality"), field_label="Nationality", max_length=100)

    def clean_religion(self):
        return clean_optional_text(self.cleaned_data.get("religion"), field_label="Religion", max_length=100)

    def clean_occupation(self):
        return clean_optional_text(self.cleaned_data.get("occupation"), field_label="Occupation", max_length=120)

    def clean_contact_number(self):
        return clean_phone_value(self.cleaned_data.get("contact_number"), required=False)

    def clean_email(self):
        return clean_email_value(self.cleaned_data.get("email"), required=True)

    def clean_precinct(self):
        return clean_optional_text(self.cleaned_data.get("precinct"), field_label="Precinct number", max_length=50)

    def clean_address_house_number(self):
        return clean_optional_text(self.cleaned_data.get("address_house_number"), field_label="House number", max_length=50)

    def clean_address_street(self):
        return clean_optional_text(self.cleaned_data.get("address_street"), field_label="Street", max_length=150)

    def clean_address_barangay(self):
        return clean_optional_text(self.cleaned_data.get("address_barangay"), field_label="Barangay", max_length=100)

    def clean_address_city(self):
        return clean_optional_text(self.cleaned_data.get("address_city"), field_label="Municipality/City", max_length=100)

    def clean_address_province(self):
        return clean_optional_text(self.cleaned_data.get("address_province"), field_label="Province", max_length=100)

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        return validate_strong_password(password)

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "middle_name",
            "last_name",
            "suffix",
            "birthdate",
            "place_of_birth",
            "gender",
            "civil_status",
            "nationality",
            "religion",
            "occupation",
            "educational_attainment",
            "contact_number",
            "email",
            "precinct",
            "permanent_address",
            "address_house_number",
            "address_street",
            "address_barangay",
            "address_city",
            "address_province",
            "pwd",
            "indigenous",
            "solo_parent",
            "voter_status",
            "status",
            "address",
            "valid_id_image",
            "consent_agreement",
            "password1",
            "password2",
        ]

    def clean(self):
        cleaned_data = super().clean()
        permanent_address = cleaned_data.get("permanent_address")
        voter_status = cleaned_data.get("voter_status")

        if permanent_address is None:
            self.add_error("permanent_address", "Select Yes or No.")

        for field_name in [
            "address_house_number",
            "address_street",
            "address_barangay",
            "address_city",
            "address_province",
        ]:
            value = cleaned_data.get(field_name)
            if isinstance(value, str):
                cleaned_data[field_name] = value.strip()

        if permanent_address:
            cleaned_data["address_barangay"] = "Gulod"
            cleaned_data["address_city"] = "Quezon City"
            cleaned_data["address_province"] = "Metro Manila"
        elif permanent_address is False:
            for field_name in [
                "address_house_number",
                "address_street",
                "address_barangay",
                "address_city",
                "address_province",
            ]:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, "This field is required.")

        if not voter_status:
            cleaned_data["precinct"] = ""

        cleaned_data["address"] = ", ".join(
            part
            for part in [
                cleaned_data.get("address_house_number"),
                cleaned_data.get("address_street"),
                cleaned_data.get("address_barangay"),
                cleaned_data.get("address_city"),
                cleaned_data.get("address_province"),
            ]
            if part
        )

        return cleaned_data


class ResidentPasswordResetForm(PasswordResetForm):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "placeholder": "Enter your username",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"
        self.fields["email"].widget.attrs.update(
            {
                "autocomplete": "email",
                "placeholder": "name@example.com",
            }
        )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        return username

    def clean_email(self):
        return clean_email_value(self.cleaned_data.get("email"), required=True)

    def get_users(self, email):
        username = (self.cleaned_data.get("username") or "").strip()
        UserModel = get_user_model()
        active_users = (
            UserModel._default_manager.filter(
                username__iexact=username,
                email__iexact=email,
                is_active=True,
                profile__isnull=False,
            )
            .select_related("profile")
            .prefetch_related("groups")
        )

        for user in active_users:
            if not user.has_usable_password():
                continue

            if not user.groups.filter(name="Resident").exists():
                continue

            yield user


class ResidentVerificationCreateForm(forms.ModelForm):
    def clean_first_name(self):
        return clean_required_text(self.cleaned_data.get("first_name"), field_label="First name", max_length=100)

    def clean_middle_name(self):
        return clean_optional_text(self.cleaned_data.get("middle_name"), field_label="Middle name", max_length=100)

    def clean_last_name(self):
        return clean_required_text(self.cleaned_data.get("last_name"), field_label="Last name", max_length=100)

    def clean_suffix(self):
        return clean_optional_text(self.cleaned_data.get("suffix"), field_label="Suffix", max_length=20)

    def clean_contact_number(self):
        return clean_phone_value(self.cleaned_data.get("contact_number"), required=False)

    def clean_email(self):
        return clean_email_value(self.cleaned_data.get("email"), required=False)

    class Meta:
        model = Resident
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "suffix",
            "birth_date",
            "gender",
            "civil_status",
            "household",
            "contact_number",
            "email",
            "voter_status",
            "status",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
        }


class ClearanceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ['purpose']


class HouseholdForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ineligible_head_ids = Household.objects.filter(
            head__isnull=False
        ).values_list("head_id", flat=True)

        eligible_heads = Resident.objects.filter(
            household__isnull=True
        ).exclude(
            id__in=ineligible_head_ids
        ).order_by("last_name", "first_name")

        if self.instance and self.instance.pk and self.instance.head_id:
            eligible_heads = (eligible_heads | Resident.objects.filter(id=self.instance.head_id)).distinct()

        self.fields["head"].queryset = eligible_heads
        self.fields["house_number"].widget.attrs.setdefault("placeholder", "e.g. 117-B")
        self.fields["street"].widget.attrs.setdefault("placeholder", "Enter street name")
        self.fields["head"].empty_label = "Select a resident"

        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} bmis-select".strip()
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} bmis-input".strip()
            if hasattr(field, "max_length") and field.max_length:
                widget.attrs.setdefault("maxlength", str(field.max_length))

    def clean_house_number(self):
        return clean_required_text(self.cleaned_data.get("house_number"), field_label="House number", max_length=20)

    def clean_street(self):
        return clean_required_text(self.cleaned_data.get("street"), field_label="Street", max_length=100)

    def clean_head(self):
        head = self.cleaned_data.get("head")
        if not head:
            return head

        if head.household_id is not None:
            raise forms.ValidationError(
                "This resident is already assigned to a household and cannot be set as head here."
            )

        already_head = Household.objects.filter(head=head)
        if self.instance and self.instance.pk:
            already_head = already_head.exclude(pk=self.instance.pk)
        if already_head.exists():
            raise forms.ValidationError(
                "This resident is already assigned as a household head."
            )

        return head

    class Meta:
        model = Household
        fields = [
            "house_number",
            "street",
            "head",
        ]


class ComplaintForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].widget.attrs.update({
            "class": "bmis-input",
            "placeholder": "Enter a clear complaint title",
        })
        self.fields["description"].widget.attrs.update({
            "class": "bmis-input",
            "placeholder": "Describe what happened, when it happened, where it happened, and any important facts.",
            "rows": 7,
        })
        resident_widget = self.fields["resident"].widget
        existing = resident_widget.attrs.get("class", "")
        resident_widget.attrs["class"] = f"{existing} bmis-select".strip()
        self.fields["title"].widget.attrs.setdefault("maxlength", "200")

    def clean_title(self):
        return clean_required_text(self.cleaned_data.get("title"), field_label="Complaint title", max_length=200)

    def clean_description(self):
        description = clean_required_text(
            self.cleaned_data.get("description"),
            field_label="Description",
        )
        if len(description) < 20:
            raise forms.ValidationError("Description must be at least 20 characters.")
        return description

    class Meta:
        model = Complaint
        fields = ["resident", "title", "description"]


class ServiceRequestRequirementsForm(forms.Form):
    requirements_note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        label="Needed requirements",
    )
    requirements_submission_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Submission instructions",
    )
    requirements_deadline = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Deadline",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} bmis-input".strip()

    def clean_requirements_note(self):
        return clean_required_text(self.cleaned_data.get("requirements_note"), field_label="Needed requirements")


class ServiceRequestResidentSubmissionForm(forms.Form):
    resident_response_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Resident note",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} bmis-input".strip()

    def clean_resident_response_note(self):
        return clean_optional_text(self.cleaned_data.get("resident_response_note"), field_label="Resident note")
