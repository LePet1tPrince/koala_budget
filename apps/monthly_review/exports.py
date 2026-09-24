import csv

from django.http import HttpResponse

from .services.review import build_review


def _decimal_str(value):
    return f"{value:.2f}" if value is not None else "0.00"


def export_monthly_review_csv(book, month) -> HttpResponse:
    """CSV of the month's budget breakdown, following apps.reports.exports's pattern."""
    review = build_review(book, month)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="monthly_review_{month.isoformat()}.csv"'

    writer = csv.writer(response)
    writer.writerow([f"Monthly Review: {review['month_label']}"])
    writer.writerow([])

    writer.writerow(["Group", "Category", "Assigned", "Spent", "Last Month", "Available", "Items"])
    for group in review["budget"]["groups"]:
        for category in group["categories"]:
            writer.writerow(
                [
                    group["name"],
                    category["name"],
                    _decimal_str(category["assigned"]),
                    _decimal_str(category["spent"]),
                    _decimal_str(category["prev"]),
                    _decimal_str(category["available"]),
                    category["count"],
                ]
            )
    writer.writerow([])
    totals = review["budget"]["totals"]
    writer.writerow(
        [
            "",
            "Total",
            _decimal_str(totals.get("assigned")),
            _decimal_str(totals.get("spent")),
            "",
            _decimal_str(totals.get("available")),
        ]
    )
    writer.writerow([])

    current = review["current"]
    writer.writerow(["Income", "Spend", "Net", "Saved", "Savings Rate %"])
    writer.writerow(
        [
            _decimal_str(current["income"]),
            _decimal_str(current["spend"]),
            _decimal_str(current["net"]),
            _decimal_str(current["saved"]),
            f"{current['savings_rate']:.1f}",
        ]
    )

    return response
