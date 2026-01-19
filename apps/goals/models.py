from django.db import models
from django.urls import reverse

from apps.teams.models import BaseTeamModel


class Goal(BaseTeamModel):
    """ A goal model for things the user is saving for """
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    goal_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Goal amount")
    target_date = models.DateField(null=True, blank=True, help_text="Due date for the goal")

    def __str__(self):
        return f"{self.name} - ${self.goal_amount}"

    def get_absolute_url(self):
        return reverse("goals:goal_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})


class GoalProgress(BaseTeamModel):
    """ A model for tracking progress towards a goal """
    goal = models.ForeignKey(
        Goal, on_delete=models.CASCADE, related_name="progress", help_text="Goal this progress is for"
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Amount saved so far")
    date = models.DateField(help_text="Date this progress was recorded")

    def __str__(self):
        return f"{self.goal} - ${self.amount}"
