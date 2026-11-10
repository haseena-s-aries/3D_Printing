import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class EmailUserManager(UserManager):
    def create_user(self, email, password=None, **extra):
        extra.setdefault("username", email)
        return super().create_user(email=email, password=password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("username", email)
        return super().create_superuser(email=email, password=password, **extra)


class User(AbstractUser):
    """Platform user. Signs in with email. Tenant access comes only from tenancy.Membership."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]
    objects = EmailUserManager()

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)
