from datetime import date, timedelta

from django import forms
from django.utils.translation import gettext_lazy as _


class IncomeStatementForm(forms.Form):
    PERIOD_CHOICES = [
        ('this_month', _('This Month')),
        ('last_3_months', _('Last 3 Months')),
        ('this_year', _('This Year')),
        ('custom', _('Custom Date Range')),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        initial='this_month',
        widget=forms.RadioSelect,
        label=_('Time Period')
    )

    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        label=_('Start Date')
    )

    end_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        label=_('End Date')
    )

    def clean(self):
        cleaned_data = super().clean()
        period = cleaned_data.get('period')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if period == 'custom':
            if not start_date:
                raise forms.ValidationError(_('Start date is required for custom period'))
            if not end_date:
                raise forms.ValidationError(_('End date is required for custom period'))
            if start_date and end_date and start_date > end_date:
                raise forms.ValidationError(_('Start date must be before end date'))

        return cleaned_data

    def get_date_range(self):
        period = self.cleaned_data['period']
        today = date.today()

        if period == 'this_month':
            start_date = today.replace(day=1)
            end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        elif period == 'last_3_months':
            end_date = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            start_date = (end_date - timedelta(days=90)).replace(day=1)
        elif period == 'this_year':
            start_date = today.replace(month=1, day=1)
            end_date = today.replace(month=12, day=31)
        else:  # custom
            start_date = self.cleaned_data['start_date']
            end_date = self.cleaned_data['end_date']

        return start_date, end_date


class BalanceSheetForm(forms.Form):
    as_of_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=date.today,
        label=_('As of Date')
    )


class NetWorthTrendForm(forms.Form):
    num_months = forms.IntegerField(
        min_value=1,
        max_value=60,
        initial=12,
        label=_('Number of Months'),
        help_text=_('How many months of data to display (1-60)')
    )
