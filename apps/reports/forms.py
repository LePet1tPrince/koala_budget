from datetime import date, timedelta

from django import forms
from django.utils.translation import gettext_lazy as _


class IncomeStatementForm(forms.Form):
    PERIOD_CHOICES = [
        ('this_month', _('This Month')),
        ('last_month', _('Last Month')),
        ('last_3_months', _('Last 3 Months')),
        ('this_year', _('This Year')),
        ('last_year', _('Last Year')),
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
        ## The filter should be the first day you want to include
        ## and the end date is the first day you want to EXCLUDE.
        current_month_first = today.replace(day=1)
        if period == 'this_month':
            start_date = current_month_first
            end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        elif period == 'last_month':
            start_date = (current_month_first - timedelta(days=1)).replace(day=1)
            end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        elif period == 'last_3_months':
            start_date = (current_month_first - timedelta(days=80)).replace(day=1)
            end_date = current_month_first - timedelta(days=1)
        elif period == 'this_year':
            start_date = today.replace(month=1, day=1)
            end_date = today.replace(month=12, day=31)
        elif period == 'last_year':
            start_date = today.replace(year=today.year - 1).replace(month=1, day=1)
            end_date = today.replace(month=1, day=1) - timedelta(days=1)
        else:  # custom
            start_date = self.cleaned_data['start_date']
            end_date = self.cleaned_data['end_date'] + timedelta(days=1)

        return start_date, end_date


class BalanceSheetForm(forms.Form):
    as_of_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=date.today,
        label=_('As of Date')
    )


class NetWorthTrendForm(forms.Form):
    start_month = forms.CharField(
        widget=forms.TextInput(attrs={'type': 'month'}),
        initial=lambda: (date.today() - timedelta(days=365)).replace(day=1).strftime('%Y-%m'),
        label=_('Start Month')
    )

    end_month = forms.CharField(
        widget=forms.TextInput(attrs={'type': 'month'}),
        initial=lambda: (date.today().replace(day=1) - timedelta(days=1)).strftime('%Y-%m'),
        label=_('End Month')
    )

    def clean(self):
        cleaned_data = super().clean()
        start_month_str = cleaned_data.get('start_month')
        end_month_str = cleaned_data.get('end_month')

        if start_month_str and end_month_str:
            try:
                # Parse YYYY-MM format
                start_year, start_month_num = map(int, start_month_str.split('-'))
                end_year, end_month_num = map(int, end_month_str.split('-'))

                # Create start_date as first day of start month
                start_date = date(start_year, start_month_num, 1)

                # Create end_date as last day of end month
                if end_month_num == 12:
                    end_date = date(end_year + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = date(end_year, end_month_num + 1, 1) - timedelta(days=1)

                # Validate that start month is before end month
                if start_date > end_date:
                    raise forms.ValidationError(_('Start month must be before end month'))

                # Replace the string values with parsed dates for the view
                cleaned_data['start_date'] = start_date
                cleaned_data['end_date'] = end_date

            except (ValueError, IndexError):
                raise forms.ValidationError(_('Invalid month format'))

        return cleaned_data
