/* globals gettext */

import AccountCard from "./AccountCard"
import { useState, useMemo } from "react"
import Icon from '../../common/Icon';

const TYPE_ICONS = { asset: 'university', liability: 'credit-card' }

function InstitutionFilter({ options, selected, onSelect }) {
  if (options.length <= 1) return null
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-base-content/70 font-medium whitespace-nowrap">{gettext('Institution')}:</span>
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
        <Icon name={icon} className="inline-block w-3.5 h-3.5 shrink-0 text-base-content/40" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-base-content/70">{title}</h3>
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

  // One section per account group (Bank Accounts, Credit Cards, Investments, …).
  // The server already orders accounts by type, then group, then account (the
  // accounts board order), so sections appear in first-seen order.
  const sections = useMemo(() => {
    const byGroup = new Map()
    filteredAccounts.forEach((a) => {
      const key = a.account_group ?? 'none'
      if (!byGroup.has(key)) {
        byGroup.set(key, {
          key,
          title: a.account_group_name || gettext('Other'),
          icon: TYPE_ICONS[a.account_type] || 'folder',
          accounts: [],
        })
      }
      byGroup.get(key).accounts.push(a)
    })
    return [...byGroup.values()]
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
