/**
 * Utility for generating grouped category options from accounts.
 * Groups accounts by type in order: Expense, Income, Transfers (Asset+Liability), Equity
 */

// Order of account type groups for display
const GROUP_ORDER = ['expense', 'income', 'transfer', 'goal'];

// Map account types to display labels
const GROUP_LABELS = {
  expense: 'Expense',
  income: 'Income',
  transfer: 'Transfer',
  goal: 'Goal',
};

/**
 * Get the group key for an account type.
 * Assets and Liabilities are combined into 'transfer'.
 */
function getGroupKey(accountType) {
  if (accountType === 'asset' || accountType === 'liability') {
    return 'transfer';
  }
  return accountType;
}

/**
 * Build grouped category options from an accounts array.
 *
 * @param {Array} accounts - Array of account objects from API
 * @param {Object} options - Configuration options
 * @param {number} options.excludeId - Account ID to exclude from the list
 * @param {Array} options.filterTypes - Array of account types to include (e.g., ['expense', 'income'])
 * @returns {Array} Array of option objects with groupLabel for Autocomplete groupBy
 */
export function buildCategoryOptions(accounts, options = {}) {
  const { excludeId, filterTypes } = options;

  if (!Array.isArray(accounts)) {
    return [];
  }

  // Filter and map accounts
  const filtered = accounts.filter((account) => {
    // Exclude by ID if specified
    if (excludeId !== undefined && account.id === excludeId) {
      return false;
    }

    // Filter by account type if specified
    if (filterTypes && filterTypes.length > 0) {
      const accountType = account.account_type || account.accountType;
      return filterTypes.includes(accountType);
    }

    return true;
  });

  // Map to option objects with group information
  const options_list = filtered.map((account) => {
    const accountType = account.account_type || account.accountType;
    const accountNumber = account.account_number || account.accountNumber;
    const groupKey = getGroupKey(accountType);
    const groupLabel = GROUP_LABELS[groupKey] || accountType;

    return {
      id: account.id,
      label: `${accountNumber} - ${account.name}`,
      accountNumber: accountNumber,
      name: account.name,
      accountType: accountType,
      groupKey: groupKey,
      groupLabel: groupLabel,
      // Sort priority based on group order
      groupOrder: GROUP_ORDER.indexOf(groupKey),
    };
  });

  // Sort by group order, then by account number within each group
  return options_list.sort((a, b) => {
    // First sort by group
    if (a.groupOrder !== b.groupOrder) {
      return a.groupOrder - b.groupOrder;
    }
    // Then sort by account number within group
    return String(a.accountNumber).localeCompare(String(b.accountNumber), undefined, { numeric: true });
  });
}

/**
 * Hook-friendly wrapper for buildCategoryOptions.
 * Use inside useMemo for memoization.
 *
 * Example:
 *   const categoryOptions = useMemo(
 *     () => buildCategoryOptions(allAccounts),
 *     [allAccounts]
 *   );
 */
export default buildCategoryOptions;
