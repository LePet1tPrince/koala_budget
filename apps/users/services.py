import csv
import io
import json
import zipfile

from apps.accounts.models import Account, AccountGroup, Payee
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.plaid.models import PlaidAccount, PlaidItem
from apps.teams.models import Membership


def export_user_data(user):
    """Export all user data as a ZIP archive containing CSV files.

    Returns a BytesIO buffer containing the ZIP file.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # User profile
        zf.writestr("profile.json", json.dumps({
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "language": user.language or "",
            "timezone": user.timezone or "",
            "date_joined": user.date_joined.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else "",
        }, indent=2))

        # Get all teams the user belongs to
        memberships = Membership.objects.filter(user=user).select_related("team")
        teams = [m.team for m in memberships]

        zf.writestr("teams.csv", _build_csv(
            ["team_name", "team_slug", "role", "joined"],
            [[m.team.name, m.team.slug, m.role, m.created_at.isoformat()] for m in memberships],
        ))

        for team in teams:
            prefix = f"team_{team.slug}"

            # Account groups
            groups = AccountGroup.objects.filter(team=team)
            zf.writestr(f"{prefix}/account_groups.csv", _build_csv(
                ["name", "account_type", "description"],
                [[g.name, g.account_type, g.description] for g in groups],
            ))

            # Accounts
            accounts = Account.objects.filter(team=team).select_related("account_group")
            zf.writestr(f"{prefix}/accounts.csv", _build_csv(
                ["account_number", "name", "account_group", "has_feed"],
                [[a.account_number, a.name, a.account_group.name, a.has_feed] for a in accounts],
            ))

            # Payees
            payees = Payee.objects.filter(team=team)
            zf.writestr(f"{prefix}/payees.csv", _build_csv(
                ["name"],
                [[p.name] for p in payees],
            ))

            # Journal entries
            entries = JournalEntry.objects.filter(team=team).select_related("payee")
            zf.writestr(f"{prefix}/journal_entries.csv", _build_csv(
                ["id", "entry_date", "payee", "description", "source", "status", "created_at"],
                [
                    [e.id, e.entry_date.isoformat(), e.payee.name if e.payee else "", e.description, e.source, e.status, e.created_at.isoformat()]
                    for e in entries
                ],
            ))

            # Journal lines
            lines = JournalLine.objects.filter(team=team).select_related("journal_entry", "account")
            zf.writestr(f"{prefix}/journal_lines.csv", _build_csv(
                ["entry_id", "entry_date", "account", "dr_amount", "cr_amount", "is_cleared", "is_reconciled"],
                [
                    [ln.journal_entry_id, ln.journal_entry.entry_date.isoformat(), str(ln.account), str(ln.dr_amount), str(ln.cr_amount), ln.is_cleared, ln.is_reconciled]
                    for ln in lines
                ],
            ))

            # Budgets
            budgets = Budget.objects.filter(team=team).select_related("category")
            zf.writestr(f"{prefix}/budgets.csv", _build_csv(
                ["month", "category", "budget_amount"],
                [[b.month.isoformat(), b.category.name, str(b.budget_amount)] for b in budgets],
            ))

            # Goals
            goals = Goal.objects.filter(team=team)
            zf.writestr(f"{prefix}/goals.csv", _build_csv(
                ["name", "description", "target_amount", "target_date", "is_complete", "is_archived"],
                [[g.name, g.description, str(g.target_amount), g.target_date.isoformat() if g.target_date else "", g.is_complete, g.is_archived] for g in goals],
            ))

            # Goal allocations
            allocations = GoalAllocation.objects.filter(team=team).select_related("goal")
            zf.writestr(f"{prefix}/goal_allocations.csv", _build_csv(
                ["goal", "month", "amount", "notes"],
                [[a.goal.name, a.month.isoformat(), str(a.amount), a.notes] for a in allocations],
            ))

            # Plaid items
            plaid_items = PlaidItem.objects.filter(team=team)
            zf.writestr(f"{prefix}/plaid_items.csv", _build_csv(
                ["institution_name", "created_at"],
                [[pi.institution_name, pi.created_at.isoformat()] for pi in plaid_items],
            ))

            # Plaid accounts
            plaid_accounts = PlaidAccount.objects.filter(team=team).select_related("item")
            zf.writestr(f"{prefix}/plaid_accounts.csv", _build_csv(
                ["institution", "name", "type", "subtype", "mask"],
                [[pa.item.institution_name, pa.name, pa.type or "", pa.subtype or "", pa.mask or ""] for pa in plaid_accounts],
            ))

    buffer.seek(0)
    return buffer


def _build_csv(headers, rows):
    """Build a CSV string from headers and rows."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def delete_user_account(user):
    """Permanently delete a user account and all associated data.

    For teams where the user is the sole admin, the entire team and its
    data are deleted. Models with PROTECT foreign keys must be deleted
    in dependency order before the team itself can be removed.
    For teams with other admins, only the user's membership is removed.
    """
    memberships = Membership.objects.filter(user=user).select_related("team")

    for membership in memberships:
        team = membership.team
        admin_count = Membership.objects.filter(team=team, role="admin").count()

        if admin_count <= 1 and membership.role == "admin":
            # Sole admin — delete all team data in dependency order to
            # respect PROTECT foreign keys, then delete the team.
            PlaidAccount.objects.filter(team=team).delete()
            PlaidItem.objects.filter(team=team).delete()
            JournalLine.objects.filter(team=team).delete()
            JournalEntry.objects.filter(team=team).delete()
            Account.objects.filter(team=team).delete()
            AccountGroup.objects.filter(team=team).delete()
            Payee.objects.filter(team=team).delete()
            team.delete()
        else:
            # Other admins exist — just remove this user's membership
            membership.delete()

    # Delete the user account itself
    user.delete()
