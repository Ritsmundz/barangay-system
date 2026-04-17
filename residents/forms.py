from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Complaint, Household, Resident, ServiceRequest


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
        })
        self.fields["email"].widget.attrs.update({
            "placeholder": "name@example.com",
            "type": "email",
            "autocomplete": "email",
        })
        self.fields["precinct"].widget.attrs.setdefault("placeholder", "Enter precinct number")
        self.fields["birth_date"].widget.attrs.update({
            "max": date.today().isoformat(),
        })
        self.fields["household"].queryset = Household.objects.order_by("house_number", "street")
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


class ResidentPortalRegistrationForm(UserCreationForm):
    CIVIL_STATUS_CHOICES = ResidentForm.CIVIL_STATUS_CHOICES

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
    pwd = forms.BooleanField(required=False)
    indigenous = forms.BooleanField(required=False)
    solo_parent = forms.BooleanField(required=False)
    voter_status = forms.BooleanField(required=False)
    status = forms.ChoiceField(choices=Resident.STATUS_CHOICES, required=False, initial="Alive")
    address = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    valid_id_image = forms.ImageField()

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
        self.fields["address"].widget.attrs.setdefault("autocomplete", "street-address")
        self.fields["address"].widget.attrs.setdefault("placeholder", "House number, street, subdivision, city")
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
        self.fields["birthdate"].widget.attrs.setdefault("max", date.today().isoformat())
        self.fields["contact_number"].widget.attrs.setdefault("autocomplete", "tel")
        self.fields["valid_id_image"].widget.attrs.setdefault("accept", "image/*")

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
            "pwd",
            "indigenous",
            "solo_parent",
            "voter_status",
            "status",
            "address",
            "valid_id_image",
            "password1",
            "password2",
        ]


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
        email = (self.cleaned_data.get("email") or "").strip().lower()
        return email

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
            "purok",
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
