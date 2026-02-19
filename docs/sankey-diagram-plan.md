# Plan: Add Sankey Diagram to Income Statement

## Overview
Add a Sankey diagram to the income statement report showing the flow of money from income sources through to expense categories, with net profit/loss allocated to "Savings".

## Files to Modify
1. `package.json` — add `chartjs-chart-sankey` dependency
2. `assets/javascript/reports/income-statement-sankey.js` — **new file**, chart rendering logic
3. `templates/reports/income_statement.html` — add canvas element and load the new JS
4. `vite.config.ts` — add new entry point for the sankey JS

## Implementation Steps

### Step 1: Install `chartjs-chart-sankey`
Run `npm install chartjs-chart-sankey` in the project root.

### Step 2: Create `assets/javascript/reports/income-statement-sankey.js`
Follow the same vanilla JS pattern used in `net_worth_trend.html` + `charts.js`:
- Import `Chart` from `chart.js/auto`
- Import `chartjs-chart-sankey` (side-effect import to register the controller)
- On `DOMContentLoaded`, read the report data from a `<script type="application/json">` tag (using Django's `json_script` filter)
- Build the Sankey dataset:
  - Each income account → "Income" (flow = account amount)
  - "Income" → each expense account (flow = account amount)
  - If net profit > 0: "Income" → "Savings" (flow = net_profit)
  - If net profit < 0: "Deficit" → "Income" (flow = abs(net_profit)), so the flows balance
- Render on the `#sankey-chart` canvas

### Step 3: Update `templates/reports/income_statement.html`
- Add a new card section above the existing tables (inside the `{% if report_data %}` block) with a canvas element (`id="sankey-chart"`)
- Serialize the report data for JS consumption using `{{ sankey_data|json_script:'sankey-data' }}`
- Load the new JS file: `{% vite_asset 'assets/javascript/reports/income-statement-sankey.js' %}`

### Step 4: Prepare `sankey_data` in the Django view
In `apps/reports/views.py`, build a serializable list from `report_data` to pass to the template context as `sankey_data`. This avoids needing to serialize Django model objects directly. Structure:
```python
sankey_data = {
    'income': [{'name': item['account'].name, 'amount': float(item['amount'])} for item in report_data['income']],
    'expenses': [{'name': item['account'].name, 'amount': float(item['amount'])} for item in report_data['expenses']],
    'net_profit': float(report_data['net_profit']),
}
```

### Step 5: Add vite entry point
Add to `vite.config.ts` rollupOptions.input:
```
'income-statement-sankey': path.resolve(__dirname, './assets/javascript/reports/income-statement-sankey.js'),
```

## Sankey Flow Logic
- **Profit scenario** (net_profit >= 0): Income accounts → "Income" → Expense accounts + "Savings"
- **Loss scenario** (net_profit < 0): Income accounts → "Income" → Expense accounts, with a "Deficit" source node flowing into expenses to balance

## Verification
1. Run `npm install` to install the new dependency
2. Start vite dev server (`npm run dev`)
3. Navigate to the income statement report page
4. Verify the Sankey diagram renders with income sources on the left flowing to expense categories and savings on the right
5. Test with different date ranges to ensure data updates correctly
6. Test edge cases: no income, no expenses, net loss scenario
