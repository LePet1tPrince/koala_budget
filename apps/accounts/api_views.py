"""
API views for accounts bulk operations.
"""

import csv
import io
import json

from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.teams.mixins import LoginAndTeamRequiredMixin

from .models import Account, AccountGroup
from .serializers import AccountGroupSerializer, AccountSerializer


class AccountBulkListView(LoginAndTeamRequiredMixin, View):
    """Return all accounts and account groups for the current team as JSON."""

    def get(self, request, *args, **kwargs):
        accounts = Account.for_team.select_related("account_group").order_by(
            "account_group__account_type", "account_number"
        )
        account_groups = AccountGroup.for_team.filter(is_archived=False).order_by("account_type", "name")

        accounts_data = AccountSerializer(accounts, many=True).data
        groups_data = AccountGroupSerializer(account_groups, many=True).data

        return JsonResponse(
            {
                "accounts": list(accounts_data),
                "account_groups": list(groups_data),
            }
        )


class AccountBulkUpdateView(LoginAndTeamRequiredMixin, View):
    """Bulk update existing accounts and optionally create new ones."""

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": _("Invalid JSON.")}, status=400)

        if not isinstance(payload, list):
            return JsonResponse({"error": _("Expected a list of account objects.")}, status=400)

        # Preload valid account group IDs for this team
        valid_group_ids = set(AccountGroup.for_team.values_list("id", flat=True))

        errors = []
        to_update = []
        to_create = []

        for i, item in enumerate(payload):
            row_num = i + 1
            name = (item.get("name") or "").strip()
            account_number = (item.get("account_number") or "").strip()
            account_group_id = item.get("account_group")
            has_feed = bool(item.get("has_feed", False))
            account_id = item.get("id")

            if not name:
                errors.append({"row": row_num, "field": "name", "error": _("Name is required.")})
                continue
            if not account_number:
                errors.append({"row": row_num, "field": "account_number", "error": _("Account number is required.")})
                continue
            if not account_group_id or int(account_group_id) not in valid_group_ids:
                errors.append({"row": row_num, "field": "account_group", "error": _("Invalid or missing account group.")})
                continue

            entry = {
                "name": name,
                "account_number": account_number,
                "account_group_id": int(account_group_id),
                "has_feed": has_feed,
            }

            if account_id:
                entry["id"] = account_id
                to_update.append(entry)
            else:
                to_create.append(entry)

        if errors:
            return JsonResponse({"errors": errors}, status=400)

        # Verify that accounts being updated belong to this team
        if to_update:
            update_ids = [e["id"] for e in to_update]
            valid_account_ids = set(Account.for_team.filter(id__in=update_ids).values_list("id", flat=True))
            invalid = [aid for aid in update_ids if aid not in valid_account_ids]
            if invalid:
                return JsonResponse(
                    {"error": _("Some accounts do not belong to this team.")}, status=403
                )

        try:
            with transaction.atomic():
                team = request.team

                for entry in to_update:
                    Account.objects.filter(id=entry["id"]).update(
                        name=entry["name"],
                        account_number=entry["account_number"],
                        account_group_id=entry["account_group_id"],
                        has_feed=entry["has_feed"],
                    )

                for entry in to_create:
                    Account.objects.create(
                        team=team,
                        name=entry["name"],
                        account_number=entry["account_number"],
                        account_group_id=entry["account_group_id"],
                        has_feed=entry["has_feed"],
                    )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        # Return updated data
        accounts = Account.for_team.select_related("account_group").order_by(
            "account_group__account_type", "account_number"
        )
        return JsonResponse({"accounts": list(AccountSerializer(accounts, many=True).data)})


class AccountCSVExportView(LoginAndTeamRequiredMixin, View):
    """Export all accounts for the current team as a CSV file."""

    def get(self, request, *args, **kwargs):
        accounts = Account.for_team.select_related("account_group").order_by(
            "account_group__account_type", "account_number"
        )

        def generate_rows():
            yield ["id", "account_number", "name", "account_group", "account_type", "has_feed"]
            for account in accounts:
                yield [
                    account.id,
                    account.account_number,
                    account.name,
                    account.account_group.name,
                    account.account_group.account_type,
                    "true" if account.has_feed else "false",
                ]

        def stream():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            for row in generate_rows():
                writer.writerow(row)
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()

        response = StreamingHttpResponse(stream(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="accounts.csv"'
        return response


class AccountCSVImportView(LoginAndTeamRequiredMixin, View):
    """Parse a CSV file and return a preview without saving."""

    def post(self, request, *args, **kwargs):
        csv_file = request.FILES.get("file")
        if not csv_file:
            return JsonResponse({"error": _("No file uploaded.")}, status=400)

        try:
            content = csv_file.read().decode("utf-8-sig")  # utf-8-sig strips BOM from Excel exports
        except UnicodeDecodeError:
            return JsonResponse({"error": _("File must be UTF-8 encoded.")}, status=400)

        # Build lookup maps for this team's account groups
        groups_by_name = {g.name.lower(): g for g in AccountGroup.for_team.all()}
        existing_accounts_by_id = {a.id: a for a in Account.for_team.all()}

        reader = csv.DictReader(io.StringIO(content))
        required_columns = {"name", "account_number", "account_group"}
        if not required_columns.issubset({c.lower() for c in (reader.fieldnames or [])}):
            return JsonResponse(
                {"error": _("CSV must have columns: account_number, name, account_group")}, status=400
            )

        # Normalize fieldname access
        fieldnames_lower = {f.lower(): f for f in reader.fieldnames}

        valid = []
        errors = []

        for i, row in enumerate(reader, start=2):  # start=2 because row 1 is the header
            def get(col):
                return (row.get(fieldnames_lower.get(col, col)) or "").strip()

            name = get("name")
            account_number = get("account_number")
            account_group_name = get("account_group")
            has_feed_raw = get("has_feed").lower()
            has_feed = has_feed_raw in ("true", "1", "yes")
            row_id_raw = get("id")
            row_id = int(row_id_raw) if row_id_raw.isdigit() else None

            row_errors = []
            if not name:
                row_errors.append(_("Name is required."))
            if not account_number:
                row_errors.append(_("Account number is required."))

            matched_group = groups_by_name.get(account_group_name.lower())
            if not matched_group:
                row_errors.append(_("Account group '%(name)s' not found.") % {"name": account_group_name})

            if row_errors:
                errors.append({"row": i, "errors": row_errors, "data": dict(row)})
                continue

            action = "update" if (row_id and row_id in existing_accounts_by_id) else "create"

            valid.append(
                {
                    "row": i,
                    "action": action,
                    "id": row_id if action == "update" else None,
                    "name": name,
                    "account_number": account_number,
                    "account_group": matched_group.id,
                    "account_group_name": matched_group.name,
                    "account_type": matched_group.account_type,
                    "has_feed": has_feed,
                }
            )

        return JsonResponse({"valid": valid, "errors": errors})
