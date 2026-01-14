from datetime import date, timedelta

from django import forms
from django.utils.translation import gettext_lazy as _


class IncomeStatementForm(forms.Form):
    PERIOD_CHOICES = [
        ("this_month", _("This month")),
        ("last_month", _("Last month")),
        ("this_year", _("This year")),
        ("custom", _("Custom")),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        required=False,
        initial="this_month",
        widget=forms.RadioSelect,
    )

    start_date = forms.DateField(
        required=False,
        label=_("Start date"),
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "input input-bordered w-full",
            }
        ),
    )

    end_date = forms.DateField(
        required=False,
        label=_("End date"),
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "input input-bordered w-full",
            }
        ),
    )

    def get_date_range(self):
        """
        Resolve the effective start and end dates based on the selected period.
        Preset periods override manually entered dates unless 'custom' is selected.
        """
        today = date.today()
        period = self.cleaned_data.get("period")
        start = self.cleaned_data.get("start_date")
        end = self.cleaned_data.get("end_date")

        if period == "this_month":
            start = today.replace(day=1)
            end = today

        elif period == "last_month":
            first_this_month = today.replace(day=1)
            end = first_this_month - timedelta(days=1)
            start = end.replace(day=1)

        elif period == "this_year":
            start = today.replace(month=1, day=1)
            end = today

        elif period == "custom" and start and end:
            pass  # use provided values

        return start, end


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
