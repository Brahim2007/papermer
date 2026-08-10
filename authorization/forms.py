from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class SignupForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].widget.attrs.update(
            {
                "autocomplete": "name",
                "placeholder": _("Your full name"),
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "autocomplete": "email",
                "placeholder": _("you@university.edu"),
            }
        )
        self.fields["user_roles"].empty_label = _("Select your research role")
        self.fields["password1"].widget.attrs.update(
            {
                "autocomplete": "new-password",
                "placeholder": _("Create a strong password"),
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "autocomplete": "new-password",
                "placeholder": _("Repeat your password"),
            }
        )

    class Meta:
        model = User
        fields = ("full_name", "email", "user_roles", "password1", "password2")
        labels = {
            "full_name": _("Full name"),
            "email": _("Email address"),
            "user_roles": _("Research role"),
        }
        widgets = {
            "full_name": forms.TextInput(),
            "email": forms.EmailInput(),
            "user_roles": forms.Select(),
        }


class LoginForm(forms.Form):
    email = forms.EmailField(
        label=_("Email address"),
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": _("you@university.edu"),
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": _("Your password"),
            }
        ),
    )
    remember_me = forms.BooleanField(
        label=_("Keep me signed in on this device"),
        required=False,
        initial=True,
    )


# Compatibility aliases for code outside this project.
Signup = SignupForm
Login = LoginForm
