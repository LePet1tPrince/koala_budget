from django.db import models
from django.urls import reverse

from apps.teams.models import BaseTeamModel


class Goal(BaseTeamModel):
    """ A goal model for things the user is saving for """
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    goal_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Goal amount")
    target_date = models.DateField(null=True, blank=True, help_text="Due date for the goal")
    saved_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Amount saved so far")

    def __str__(self):
        return f"{self.name} - ${self.goal_amount}"

    def get_absolute_url(self):
        return reverse("goals:goal_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})
