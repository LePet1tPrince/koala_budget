This is how you imagine a
project to be in simple text
and it can be as long or
short as you want. Good
for keeping focused at the
beginning of an effort.

# Architecture

```mermaid
erDiagram
	direction TB
	payee {
		string id PK ""
		string name  ""
	}

	account {
		string id PK ""
		string name  ""
		int account_number  "1000s for assets, 2000s for liabilities, etc"
		string account_type FK " need to look up both account_type and sybtype to the same table"
		string subtype FK ""
		boolean has_feed  ""
		number account_balance  "calculated field"
	}

	account_type {
		string id PK ""
		string type_name  ""
		string subtype_name  ""
	}


	transaction {
		string id PK ""
		date date_posted  ""
		number amount  ""
		string payee_id FK ""
		string account_id FK ""
		string category_id FK ""
		string notes  ""
		date imported_on  ""
		string import_method  ""
		string status  ""
		boolean is_cleared  ""
		boolean is_reconciled  ""
	}

	budget {
		string id PK "Needs to automatically generate a new entry for every account where account_type = income or expense for each month"
		date month ""
		string category_id FK ""
		number budget ""
		number actual "Calculated. sum amount for all transactions in the given month where transaction.account_id = category_id or transaction.category_id = category_id"
		number available "budget - actual"
	}

	transaction}o--||payee:" "
	account}o--||account_type:"  "
	account||--o{transaction:" account_id"
	account||--o{transaction:" category_id"
	budget}o--||account: ""

```