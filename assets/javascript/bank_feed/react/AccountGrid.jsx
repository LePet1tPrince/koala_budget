/* globals gettext */

import AccountCard from "./AccountCard"
import { useState, useMemo } from "react"

function SlicerButtons({ label, options, selected, onSelect }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-base-content/60 font-medium whitespace-nowrap">{label}:</span>
      <div role="group" className="flex flex-wrap gap-1">
        <button
          className={`btn btn-xs ${selected === null ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => onSelect(null)}
        >
          {gettext('All')}
        </button>
        {options.map((opt) => (
          <button
            key={opt}
            className={`btn btn-xs ${selected === opt ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => onSelect(selected === opt ? null : opt)}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

function AccountGrid({ accounts, selectedAccount, handleAccountSelect }) {
  const [showMore, setShowMore] = useState(false)
  const [selectedGroup, setSelectedGroup] = useState(null)
  const [selectedInstitution, setSelectedInstitution] = useState(null)

  const groupOptions = useMemo(() => (
    [...new Set(accounts.map((a) => a.account_group_name).filter(Boolean))].sort()
  ), [accounts])

  const institutionOptions = useMemo(() => (
    [...new Set(accounts.map((a) => a.institution_name).filter(Boolean))].sort()
  ), [accounts])

  const filteredAccounts = useMemo(() => accounts.filter((a) => {
    if (selectedGroup && a.account_group_name !== selectedGroup) return false
    if (selectedInstitution && a.institution_name !== selectedInstitution) return false
    return true
  }), [accounts, selectedGroup, selectedInstitution])

  const firstRowCount = 4 // matches xl:grid-cols-4
  const visibleAccounts = filteredAccounts.slice(0, firstRowCount)
  const hiddenAccounts = filteredAccounts.slice(firstRowCount)

  const showGroupSlicer = groupOptions.length > 1
  const showInstitutionSlicer = institutionOptions.length > 1

  return (
    <div className="space-y-4">
      {/* Slicers */}
      {(showGroupSlicer || showInstitutionSlicer) && (
        <div className="flex flex-col gap-2 pb-2 border-b border-base-300">
          {showGroupSlicer && (
            <SlicerButtons
              label={gettext('Account Group')}
              options={groupOptions}
              selected={selectedGroup}
              onSelect={setSelectedGroup}
            />
          )}
          {showInstitutionSlicer && (
            <SlicerButtons
              label={gettext('Institution')}
              options={institutionOptions}
              selected={selectedInstitution}
              onSelect={setSelectedInstitution}
            />
          )}
        </div>
      )}

      {/* First row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {visibleAccounts.map((account) => (
          <AccountCard
            key={account.id}
            account={account}
            isSelected={selectedAccount?.id === account.id}
            onClick={handleAccountSelect}
          />
        ))}

        {hiddenAccounts.length > 0 && (
          <button
            onClick={() => setShowMore((v) => !v)}
            className="flex items-center justify-center rounded-xl border border-dashed border-gray-300 hover:border-gray-400 hover:bg-gray-50 transition text-sm font-medium"
          >
            {showMore ? gettext('Hide accounts') : `+${hiddenAccounts.length} ${gettext('more')}`}
          </button>
        )}
      </div>

      {/* Overflow section */}
      {showMore && hiddenAccounts.length > 0 && (
        <div className="rounded-xl border bg-gray-50 p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {hiddenAccounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                isSelected={selectedAccount?.id === account.id}
                onClick={handleAccountSelect}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default AccountGrid;
