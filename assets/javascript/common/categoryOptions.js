/* globals gettext */
/**
 * Utility for generating grouped category options from accounts.
 * Groups accounts in order: Expense, Income, Transfers (Asset+Liability), Goals, Equity.
 * System accounts are never offered.
 */
import { accountKind, goalLeftLabel, pickableAccounts } from './accountKind';

// Order of account type groups for display
const GROUP_ORDER = ['expense', 'income', 'transfer', 'goal', 'equity'];

// Map account types to display labels
const GROUP_LABELS = {
  expense: gettext('Expense'),
  income: gettext('Income'),
  transfer: gettext('Transfer'),
  goal: gettext('Goals'),
  equity: gettext('Equity'),
};

/**
 * Get the group key for an account.
 * Assets and Liabilities are combined into 'transfer'; the equity type splits
 * into real goals and plain equity.
 */
function getGroupKey(account) {
  const kind = accountKind(account);
  if (kind === 'asset' || kind === 'liability') {
    return 'transfer';
  }
  return kind;
}

/**
 * Build grouped category options from an accounts array.
 *
 * @param {Array} accounts - Array of account objects from API
 * @param {Object} options - Configuration options
 * @param {number} options.excludeId - Account ID to exclude from the list
 * @param {Array} options.filterTypes - Array of account types to include (e.g., ['expense', 'income'])
 * @param {Array} options.keep - Accounts a transaction already uses, offered even when
 *   the picker would hide them (a system category must survive an edit untouched)
 * @returns {Array} Array of option objects with groupLabel for Autocomplete groupBy
 */
export function buildCategoryOptions(accounts, options = {}) {
  const { excludeId, filterTypes, keep = [] } = options;

  if (!Array.isArray(accounts)) {
    return [];
  }

  const pickable = pickableAccounts(accounts);
  const kept = keep.filter((account) => account && !pickable.some((a) => a.id === account.id));

  // Filter and map accounts
  const filtered = [...pickable, ...kept].filter((account) => {
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
    const accountGroupName = account.account_group_name || account.accountGroupName || '';
    const groupKey = getGroupKey(account);
    const groupLabel = GROUP_LABELS[groupKey] || accountType;
    const left = goalLeftLabel(account);

    return {
      id: account.id,
      label: left ? `${account.name} · ${left}` : `${accountGroupName} - ${account.name}`,
      name: account.name,
      accountType: accountType,
      groupKey: groupKey,
      groupLabel: groupLabel,
      groupOrder: GROUP_ORDER.indexOf(groupKey),
      account,
    };
  });

  // Sort by group order, then alphabetically by name within each group
  return options_list.sort((a, b) => {
    if (a.groupOrder !== b.groupOrder) {
      return a.groupOrder - b.groupOrder;
    }
    return a.name.localeCompare(b.name);
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
