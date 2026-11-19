import copy

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.api.models import UserAPIKey

from .forms import CustomUserChangeForm, UploadAvatarForm
from .models import CustomUser

PROFILE_FORM_FIELDS = ("email", "first_name", "last_name", "language", "timezone")


class ProfileSerializer(serializers.ModelSerializer):
    """
    The signed-in user's profile. Writes are validated by the profile page's own
    form (`CustomUserChangeForm`: a required email, the site's languages, the
    time-zone list), so the page and the API accept exactly the same values.
    """

    display_name = serializers.CharField(source="get_display_name", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    email = serializers.EmailField(
        required=False,
        help_text=_("A new address is applied once confirmed from the email sent to it (when confirmation is on)."),
    )
    language = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=10)
    timezone = serializers.CharField(required=False, allow_blank=True, max_length=100)

    class Meta:
        model = CustomUser
        fields = ("id", "email", "first_name", "last_name", "display_name", "avatar_url", "language", "timezone")
        read_only_fields = ("id",)

    def get_avatar_url(self, user) -> str:
        request = self.context.get("request")
        return request.build_absolute_uri(user.avatar_url) if request else user.avatar_url

    def validate(self, attrs):
        """Run the page's form over the profile as it would be saved; report errors on the fields sent."""
        user = self.instance
        data = {field: getattr(user, field) or "" for field in PROFILE_FORM_FIELDS}
        data.update({field: value or "" for field, value in attrs.items()})
        # A copy: a bound ModelForm writes the cleaned values onto its instance.
        form = CustomUserChangeForm(data, instance=copy.copy(user))
        if not form.is_valid():
            errors = {field: messages for field, messages in form.errors.items() if field in attrs}
            if errors:
                raise serializers.ValidationError(errors)
        cleaned = {field: form.cleaned_data[field] for field in attrs if field in form.cleaned_data}
        # A field the form doesn't offer (`language` with one site language) is not saved.
        return cleaned


class ProfileUpdateSerializer(ProfileSerializer):
    """The profile after a save, and whether a new email address awaits confirmation."""

    email_confirmation_sent = serializers.SerializerMethodField()

    class Meta(ProfileSerializer.Meta):
        fields = (*ProfileSerializer.Meta.fields, "email_confirmation_sent")

    def get_email_confirmation_sent(self, user) -> bool:
        return bool(self.context.get("email_confirmation_sent"))


class AvatarUploadSerializer(serializers.Serializer):
    """A profile picture (multipart): an image file of up to 5 MB, as the profile page accepts."""

    avatar = serializers.FileField()

    def validate(self, attrs):
        form = UploadAvatarForm(files={"avatar": attrs["avatar"]})
        if not form.is_valid():
            raise serializers.ValidationError(form.errors)
        return attrs


class APIKeySerializer(serializers.ModelSerializer):
    """An API key as listed: its prefix identifies it; the key itself is never stored."""

    class Meta:
        model = UserAPIKey
        fields = ("prefix", "name", "created", "revoked")
        read_only_fields = fields


class APIKeyCreatedSerializer(APIKeySerializer):
    """A new API key, with the key itself -- the only time it is ever shown."""

    key = serializers.CharField(read_only=True, help_text=_("Save it somewhere safe: it is never shown again."))

    class Meta(APIKeySerializer.Meta):
        fields = (*APIKeySerializer.Meta.fields, "key")
        read_only_fields = fields


class DeleteAccountSerializer(serializers.Serializer):
    """
    Confirm deleting the account: the account's email typed out (as on the page),
    and the password for an account that has one. An account that signs in only
    through a social provider is asked to have re-authenticated recently instead.
    """

    confirmation = serializers.CharField(help_text=_("The account's email address, typed out."))
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
        help_text=_("Required when the account has a password."),
    )
