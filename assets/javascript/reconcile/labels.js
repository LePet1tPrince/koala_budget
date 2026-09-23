/* globals gettext */

/**
 * Wording that depends on the account type. A card statement says "balance
 * owed", "charges" and "payments"; a bank statement says "balance", "money
 * in" and "money out". The amounts are already in statement sign, so a
 * positive amount is a deposit on a bank account and a charge on a card.
 */
export const labelsFor = (account) =>
  account.is_liability
    ? {
        balance: gettext('Balance owed'),
        balanceHelp: gettext('Enter it as printed on the statement: a positive number for money you owe.'),
        plus: gettext('Charges'),
        minus: gettext('Payments'),
      }
    : {
        balance: gettext('Closing balance'),
        balanceHelp: gettext('Enter it as printed on the statement.'),
        plus: gettext('Money in'),
        minus: gettext('Money out'),
      };

export const formatDate = (iso) => {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};
