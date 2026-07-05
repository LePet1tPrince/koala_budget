/* globals gettext */

import AccountCard from "./AccountCard"
import { useState, useMemo } from "react"

const TYPE_SECTIONS = [
  { type: 'asset', icon: 'fa-university', getLabel: () => gettext('Bank Accounts') },
  { type: 'liability', icon: 'fa-credit-card', getLabel: () => gettext('Credit Cards') },
]

function InstitutionFilter({ options, selected, onSelect }) {
  if (options.length <= 1) return null
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-base-content/60 font-medium whitespace-nowrap">{gettext('Institution')}:</span>
      <div role="group" className="flex flex-wrap gap-1">
        <button
          className={`btn btn-xs rounded-full ${selected === null ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => onSelect(null)}
        >
          {gettext('All')}
        </button>
        {options.map((opt) => (
          <button
            key={opt}
            className={`btn btn-xs rounded-full ${selected === opt ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => onSelect(selected === opt ? null : opt)}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

function AccountSection({ title, icon, accounts, selectedAccount, handleAccountSelect }) {
  const reviewCount = useMemo(
    () => accounts.reduce((sum, a) => sum + (a.uncategorized_count || 0), 0),
    [accounts]
  )

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <i className={`fa ${icon} text-base-content/40 text-xs`} aria-hidden="true"></i>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-base-content/60">{title}</h3>
        <span className="text-xs text-base-content/40">({accounts.length})</span>
        {reviewCount > 0 && (
          <span className="badge badge-warning badge-xs ml-auto">
            {reviewCount} {gettext('to review')}
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
        {accounts.map((account) => (
          <AccountCard
            key={account.id}
            account={account}
            isSelected={selectedAccount?.id === account.id}
            onClick={handleAccountSelect}
          />
        ))}
      </div>
    </div>
  )
}

function AccountGrid({ accounts, selectedAccount, handleAccountSelect }) {
  const [selectedInstitution, setSelectedInstitution] = useState(null)

  const institutionOptions = useMemo(() => (
    [...new Set(accounts.map((a) => a.institution_name).filter(Boolean))].sort()
  ), [accounts])

  const filteredAccounts = useMemo(() => accounts.filter((a) => (
    !selectedInstitution || a.institution_name === selectedInstitution
  )), [accounts, selectedInstitution])

  // Group accounts by account type (bank accounts vs. credit cards) so the two
  // feed kinds are easy to tell apart at a glance, with any unexpected type
  // (feed accounts are normally asset/liability only) caught in a fallback section.
  const sections = useMemo(() => {
    const grouped = TYPE_SECTIONS.map(({ type, icon, getLabel }) => ({
      key: type,
      title: getLabel(),
      icon,
      accounts: filteredAccounts.filter((a) => a.account_type === type),
    })).filter((section) => section.accounts.length > 0)

    const knownTypes = new Set(TYPE_SECTIONS.map((s) => s.type))
    const otherAccounts = filteredAccounts.filter((a) => !knownTypes.has(a.account_type))
    if (otherAccounts.length > 0) {
      grouped.push({ key: 'other', title: gettext('Other'), icon: 'fa-folder', accounts: otherAccounts })
    }

    return grouped
  }, [filteredAccounts])

  return (
    <div className="space-y-5">
      <InstitutionFilter
        options={institutionOptions}
        selected={selectedInstitution}
        onSelect={setSelectedInstitution}
      />

      {sections.map((section) => (
        <AccountSection
          key={section.key}
          title={section.title}
          icon={section.icon}
          accounts={section.accounts}
          selectedAccount={selectedAccount}
          handleAccountSelect={handleAccountSelect}
        />
      ))}
    </div>
  )
}

export default AccountGrid;
