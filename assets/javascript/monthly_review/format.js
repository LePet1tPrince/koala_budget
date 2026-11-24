export { formatMoney as currency } from '../common/amount';

export const compactCurrency = (value) => `$${Number(value).toLocaleString()}`;

export const percent = (value, digits = 1) => `${Number(value).toFixed(digits)}%`;
