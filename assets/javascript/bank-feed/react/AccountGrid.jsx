import AccountCard from "./AccountCard"
import { useState } from "react"

function AccountGrid({ accounts, selectedAccount, handleAccountSelect }) {
  const [showMore, setShowMore] = useState(false)

  // number of cards per row by breakpoint
  const firstRowCount = 4 // matches xl:grid-cols-4

  const visibleAccounts = accounts.slice(0, firstRowCount)
  const hiddenAccounts = accounts.slice(firstRowCount)

  return (
    <div className="space-y-4">
      {/* First row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {visibleAccounts.map((account) => (
          <AccountCard
            key={account.account_id}
            account={account}
            isSelected={selectedAccount?.account_id === account.account_id}
            onClick={handleAccountSelect}
          />
        ))}

        {/* More accounts card */}
        {hiddenAccounts.length > 0 && (
          <button
            onClick={() => setShowMore((v) => !v)}
            className="flex items-center justify-center rounded-xl border border-dashed border-gray-300 hover:border-gray-400 hover:bg-gray-50 transition text-sm font-medium"
          >
            {showMore ? "Hide accounts" : `+${hiddenAccounts.length} more`}
          </button>
        )}
      </div>

      {/* Dropdown section */}
      {showMore && hiddenAccounts.length > 0 && (
        <div className="rounded-xl border bg-gray-50 p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {hiddenAccounts.map((account) => (
              <AccountCard
                key={account.account_id}
                account={account}
                isSelected={selectedAccount?.account_id === account.account_id}
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

