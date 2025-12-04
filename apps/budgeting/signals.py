"""
Signals for budgeting app.
Only handles simple calculated fields to avoid complexity.
Transaction balance updates are handled by services for better control.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Budget, Goal


@receiver(pre_save, sender=Budget)
def update_budget_calculated_fields(sender, instance, **kwargs):
    """
    Update calculated fields on budget before save.
    Only updates if fields are not already being updated to avoid infinite loop.
    """
    # Update available amount
    instance.available_amount = instance.budgeted_amount - instance.actual_amount

    # Cache category name for performance
    if instance.category_id:
        instance.category_name = instance.category.name


@receiver(pre_save, sender=Goal)
def update_goal_remaining(sender, instance, **kwargs):
    """
    Update remaining amount on goal before save.
    """
    instance.remaining_amount = instance.target_amount - instance.saved_amount
