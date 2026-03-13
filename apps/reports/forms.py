from datetime import date, timedelta

from django import forms
from django.utils.translation import gettext_lazy as _


class NetWorthTrendForm(forms.Form):
    start_month = forms.CharField(
        widget=forms.TextInput(attrs={"type": "month"}),
        initial=lambda: (date.today() - timedelta(days=365)).replace(day=1).strftime("%Y-%m"),
        label=_("Start Month"),
    )

    end_month = forms.CharField(
        widget=forms.TextInput(attrs={"type": "month"}),
        initial=lambda: (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
        label=_("End Month"),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_month_str = cleaned_data.get("start_month")
        end_month_str = cleaned_data.get("end_month")

        if start_month_str and end_month_str:
            try:
                # Parse YYYY-MM format
                start_year, start_month_num = map(int, start_month_str.split("-"))
                end_year, end_month_num = map(int, end_month_str.split("-"))

                # Create start_date as first day of start month
                start_date = date(start_year, start_month_num, 1)

                # Create end_date as last day of end month
                if end_month_num == 12:
                    end_date = date(end_year + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = date(end_year, end_month_num + 1, 1) - timedelta(days=1)

                # Validate that start month is before end month
                if start_date > end_date:
                    raise forms.ValidationError(_("Start month must be before end month"))

                # Replace the string values with parsed dates for the view
                cleaned_data["start_date"] = start_date
                cleaned_data["end_date"] = end_date

            except (ValueError, IndexError) as err:
                raise forms.ValidationError(_("Invalid month format")) from err

        return cleaned_data
