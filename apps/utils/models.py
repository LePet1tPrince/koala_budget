from django.db import models
from django.utils import timezone

class BaseModel(models.Model):
    """
    Base model that includes default created / updated timestamps.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False, help_text="Set to true to archive this item")
    archived_at = models.DateTimeField(null=True, blank=True, help_text="Date this item was archived")

    class Meta:
        abstract = True

    def archive(self):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save()

    def restore(self):
        self.is_archived = False
        self.archived_at = None
        self.save()

    @property
    def is_active(self):
        return not self.is_archived