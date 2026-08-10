from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models

from .managers import Manager


USER_ROLES = (
    ("researcher", "Researcher"),
    ("lecturer_senior", "Lecturer - Senior Lecturer"),
    ("lecturer", "Lecturer"),
    ("professor", "Professor"),
    ("librarian", "Librarian"),
    ("student_doctoral", "Student - Doctoral Student"),
    ("student_master", "Student - Master"),
    ("student_bachelor", "Student - Bachelor"),
    ("student_phd", "Student - Ph. D. Student"),
    ("other", "Other"),
)


class User(AbstractBaseUser, PermissionsMixin):
    full_name = models.CharField(max_length=100, default="")
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    email = models.EmailField(unique=True)
    user_roles = models.CharField(
        choices=USER_ROLES, max_length=20, blank=True, null=True
    )
    tags = ArrayField(
        base_field=models.CharField(max_length=100), null=True, blank=True
    )
    keywords = ArrayField(
        base_field=models.CharField(max_length=100), null=True, blank=True
    )
    authors = ArrayField(
        base_field=models.CharField(max_length=150), null=True, blank=True
    )

    objects = Manager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name", "user_roles"]

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email
