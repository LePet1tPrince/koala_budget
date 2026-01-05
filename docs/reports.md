# Reports App Documentation

The Reports app provides financial reporting functionality for teams, including income statements, balance sheets, and net worth trend analysis.

## Overview

The reports app consists of several key components:

- **Forms**: Handle user input for report parameters
- **Services**: Calculate financial data from journal entries
- **Views**: Handle HTTP requests and render templates
- **Templates**: Display reports with charts and tables

## Architecture

### Data Flow

1. **User Input**: Forms collect report parameters (dates, periods)
2. **Data Retrieval**: Services query journal entries and calculate balances
3. **Data Processing**: Services aggregate data by account types and time periods
4. **Presentation**: Templates render data as charts and tables

### Key Models

The reports app primarily works with:
- `JournalEntry`: Transaction records
- `JournalLine`: Individual debit/credit entries
- `Account`: Chart of accounts
- `AccountGroup`: Account categorization
- `Team`: Multi-tenancy support

## Components

### Forms

#### IncomeStatementForm
Handles income statement report parameters.

**Fields:**
- `period`: Choice field with predefined periods (this month, last month, etc.)
- `start_date`: Start date for custom periods
- `end_date`: End date for custom periods

**Methods:**
- `clean()`: Validates custom period dates
- `get_date_range()`: Converts period selection to actual date ranges

#### BalanceSheetForm
Handles balance sheet report parameters.

**Fields:**
- `as_of_date`: Date for balance sheet snapshot

#### NetWorthTrendForm
Handles net worth trend report parameters.

**Fields:**
- `start_month`: Start month in YYYY-MM format
- `end_month`: End month in YYYY-MM format

**Methods:**
- `clean()`: Parses month strings to date objects and validates ranges

### Services

#### ReportService

Main service class for calculating financial reports.

**Methods:**

##### `get_income_statement_data(start_date, end_date)`
Calculates income and expense data for a date range.

**Returns:**
```python
{
    'income': [{'account': Account, 'amount': Decimal}, ...],
    'expenses': [{'account': Account, 'amount': Decimal}, ...],
    'total_income': Decimal,
    'total_expenses': Decimal,
    'net_profit': Decimal
}
```

##### `get_balance_sheet_data(as_of_date)`
Calculates balance sheet data as of a specific date.

**Returns:**
```python
{
    'assets': [{'account': Account, 'amount': Decimal}, ...],
    'liabilities': [{'account': Account, 'amount': Decimal}, ...],
    'equity': [{'account': Account, 'amount': Decimal}, ...],
    'total_assets': Decimal,
    'total_liabilities': Decimal,
    'total_equity': Decimal,
    'net_worth': Decimal
}
```

##### `get_net_worth_trend_data_by_date_range(start_date, end_date)`
Calculates net worth trend data for a date range, showing monthly values.

**Returns:**
```python
[
    {'date': date, 'net_worth': Decimal},
    ...
]
```

### Views

#### reports_home
Landing page for reports section.

#### income_statement
Income statement report view.

**GET Parameters:**
- `period`: Report period
- `start_date`: Custom start date
- `end_date`: Custom end date

#### balance_sheet
Balance sheet report view.

**GET Parameters:**
- `as_of_date`: Balance sheet date

#### net_worth_trend
Net worth trend report view.

**GET Parameters:**
- `start_month`: Start month (YYYY-MM)
- `end_month`: End month (YYYY-MM)

### Templates

#### reports_home.html
Navigation page for different reports.

#### income_statement.html
Income statement with transaction tables and summary.

#### balance_sheet.html
Balance sheet with asset/liability/equity sections.

#### net_worth_trend.html
Net worth trend with line chart and monthly data table.

## Chart Implementation

The reports app uses Chart.js for data visualization through the pegasus charts system:

- **Charts Module**: `assets/javascript/pegasus/examples/charts.js`
- **Integration**: `SiteJS.pegasus.Charts.renderChart(type, elementId, data, showLegend)`
- **Data Format**: `[[label, value], [label, value], ...]`

### Chart Types

- **Line Charts**: Net worth trends over time
- **Bar Charts**: Department spending, salary comparisons
- **Pie Charts**: Budget allocation visualization

## URL Configuration

```python
urlpatterns = [
    path('', views.reports_home, name='reports_home'),
    path('income-statement/', views.income_statement, name='income_statement'),
    path('balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('net-worth-trend/', views.net_worth_trend, name='net_worth_trend'),
]
```

## Testing

The reports app includes comprehensive tests covering:

### Unit Tests
- **ReportServiceTest**: Service method functionality
- **Form Tests**: Validation and data processing
- **View Tests**: HTTP responses and context data

### Test Data Setup
Tests create realistic financial data including:
- Account groups and accounts
- Journal entries with various transaction types
- Multi-month data for trend analysis

### Running Tests
```bash
# Run all report tests
python manage.py test apps.reports

# Run specific test class
python manage.py test apps.reports.tests.ReportServiceTest

# Run specific test method
python manage.py test apps.reports.tests.ReportServiceTest.test_income_statement_data_basic
```

## Accounting Principles

The reports follow standard accounting principles:

### Income Statement
- **Revenue Recognition**: Income accounts use credit balances
- **Expense Recognition**: Expense accounts use debit balances
- **Net Profit**: Total income minus total expenses

### Balance Sheet
- **Asset Valuation**: Debit balances represent asset values
- **Liability Recording**: Credit balances represent obligations
- **Equity Calculation**: Assets minus liabilities
- **Net Worth**: Equity balance

### Net Worth Trends
- **Monthly Calculation**: End-of-month balance snapshots
- **Cumulative Tracking**: Shows net worth changes over time
- **Date Range Flexibility**: Customizable reporting periods

## Security Considerations

- **Team Isolation**: All queries filter by team membership
- **User Authorization**: Views require login and team access
- **Data Validation**: Form validation prevents invalid date ranges
- **SQL Injection Prevention**: Django ORM handles query safety

## Performance Optimization

- **Database Indexing**: Journal entries indexed by team and date
- **Query Optimization**: Select_related for account/group joins
- **Efficient Aggregation**: Database-level SUM operations
- **Pagination Ready**: Large datasets can be paginated

## Future Enhancements

Potential improvements for the reports app:

- **Export Functionality**: PDF/Excel report generation
- **Scheduled Reports**: Automated report delivery
- **Custom Date Ranges**: More flexible period selection
- **Comparative Analysis**: Year-over-year comparisons
- **Budget vs Actual**: Budget performance tracking
- **Multi-currency Support**: Currency conversion for reports
- **Real-time Updates**: WebSocket-based live data updates
