from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

from apps.common.models import TimeStampedModel
from apps.institutions.models import Institution


class UserManager(BaseUserManager):
    use_in_migrations = True

    @staticmethod
    def normalize_email_address(email):
        return (email or "").strip().lower()

    def get_by_natural_key(self, username):
        return self.get(email=self.normalize_email_address(username))

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email_address(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_platform_admin", True)
        return self.create_user(email, password, **extra)


class User(TimeStampedModel, AbstractBaseUser):
    """Login identity only. Departmental membership and roles live in their own tables."""

    class AuthProvider(models.TextChoices):
        LOCAL = "local"
        INSTITUTIONAL_SSO = "institutional_sso", "Institutional SSO"
        OTHER = "other"

    email = models.EmailField(max_length=254, unique=True)
    is_active = models.BooleanField(default=True)
    is_platform_admin = models.BooleanField(default=False)
    auth_provider = models.CharField(max_length=40, choices=AuthProvider, default=AuthProvider.LOCAL)
    last_login = models.DateTimeField(db_column="last_login_at", null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        ordering = ["email"]
        constraints = [models.UniqueConstraint(Lower("email"), name="uq_user_email_lower")]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email_address(self.email)
        super().save(*args, **kwargs)

    # Django admin access is limited to platform administrators. Finance models are
    # registered read-only, so this never confers spending or approval authority.
    @property
    def is_staff(self):
        return self.is_active and self.is_platform_admin

    @property
    def is_superuser(self):
        return False

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_perms(self, perm_list, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    @property
    def display_name(self):
        profile = getattr(self, "profile", None)
        if profile:
            return profile.display_name or profile.full_name
        return self.email

    def get_full_name(self):
        return self.display_name

    def get_short_name(self):
        profile = getattr(self, "profile", None)
        return profile.given_name if profile else self.email


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="profiles")
    student_number = models.CharField(max_length=80, null=True, blank=True)
    given_name = models.CharField(max_length=100)
    family_name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200, null=True, blank=True)
    phone_number = models.CharField(max_length=40, null=True, blank=True)
    preferred_language = models.CharField(max_length=20, null=True, blank=True, default="en")
    # Not in the workbook: delivery preferences used by reminders and receipts.
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)

    class Meta:
        db_table = "user_profiles"
        ordering = ["family_name", "given_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "student_number"],
                condition=models.Q(student_number__isnull=False),
                name="uq_student_number_per_institution",
            )
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.given_name} {self.family_name}".strip()
