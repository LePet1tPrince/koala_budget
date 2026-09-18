export const currency = (value) => {
  const n = Number(value) || 0;
  const sign = n < 0 ? '-' : '';
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const compactCurrency = (value) => `$${Number(value).toLocaleString()}`;

export const percent = (value, digits = 1) => `${Number(value).toFixed(digits)}%`;
