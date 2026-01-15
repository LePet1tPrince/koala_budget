# Bank Feed & Ledger Architecture – Conceptual Plan

## Overview
This document describes the **conceptual architecture** for handling transactions from multiple sources (Manual input, Plaid, CSV upload) in a Django-based finance application that uses **double-entry accounting**.

The primary goal of this design is to:
- Keep the **ledger clean and authoritative**
- Support **multiple ingestion workflows** without duplication
- Maintain a **single, consistent categorization experience**
- Avoid tight coupling between bank data and accounting data
- Scale cleanly to transfers, splits, reconciliation, and future data sources

This plan intentionally focuses on *why* decisions were made rather than *how* they are implemented.

---

## Core Design Principle

> **Separate bank-side reality from accounting interpretation.**

Not all financial data is accounting data.

- Bank feeds represent *what happened at a financial institution*
- The ledger represents *how the user interprets that activity for accounting purposes*

Mixing these responsibilities leads to brittle logic, duplicated models, and hard-to-maintain workflows.

---

## Key Conceptual Objects

### 1. Bank Feed Transactions (Imported Transactions)

**Purpose:**
Represent a single movement of money *from the perspective of a specific financial account*.

**Key characteristics:**
- One row per account per transaction
- Exists regardless of source (Manual, Plaid, CSV)
- May or may not be categorized
- Drives all bank-feed and categorization UX

This object answers the question:
> "What did the bank say happened in this account?"

---

### 2. Journal Entries (Accounting Events)

**Purpose:**
Represent a complete, balanced accounting interpretation of one economic event.

**Key characteristics:**
- Always balanced (total debits = total credits)
- Created only when a transaction is categorized
- Can explain one or many bank feed transactions
- Never appear directly in bank feed UX

This object answers the question:
> "What does this transaction *mean* from an accounting perspective?"

---

### 3. Journal Lines (Ledger Legs)

**Purpose:**
Represent individual debit or credit legs of a journal entry.

**Key characteristics:**
- Ledger-only concept
- Used for reporting, balances, and reconciliation
- Support split transactions naturally
- Never drive categorization UX

---

## Why This Separation Matters

### Avoids Premature Ledger Pollution
- Plaid and CSV data is often incomplete or ambiguous
- Ledger entries should only exist once intent is clear
- Imported transactions act as a staging area

### Enables a Single Categorization Workflow
- Categorization UI works against **one object type**
- Source-specific logic stays out of the UI
- New ingestion sources can be added without UI changes

### Preserves Accounting Integrity
- Ledger is always balanced
- Splits and transfers are modeled correctly
- Reporting logic stays simple and correct

---

## How the Three Workflows Fit

### 1. Manual Entry
**Priority:** Immediate accuracy

- User explicitly defines intent
- A bank feed transaction is created
- A journal entry is created immediately
- Both are linked

This ensures:
- Transfers work correctly
- Reconciliation remains consistent
- Manual entries behave like imported ones

---

### 2. Plaid Import
**Priority:** Review before commitment

- Transactions enter the system as bank feed items only
- No ledger impact initially
- User categorizes later
- Ledger entries are created on categorization

This mirrors real-world accounting software behavior.

---

### 3. CSV Upload
**Priority:** Flexibility

- CSV rows are normalized into bank feed transactions
- Users may:
  - Categorize later (same as Plaid)
  - Categorize during import (power users)

Even when categorized immediately, the bank feed record still exists to preserve consistency.

---

## Transfers: A First-Class Concept

Transfers are **not special cases** in this design.

- One real-world transfer affects two accounts
- This results in two bank feed transactions
- Both point to the same journal entry

This cleanly models:
- Internal transfers
- Credit card payments
- Inter-bank movements

---

## Split Transactions

Splits are handled entirely at the ledger level:

- One bank feed transaction
- One journal entry
- Multiple journal lines

The bank feed remains simple while the ledger captures complexity.

---

## Bank Feed UX Philosophy

The bank feed is always driven by **bank feed transactions**, never journal lines.

- Uncategorized view: shows items without accounting meaning yet
- Categorized view: shows the same items, now enriched with accounting details

This prevents:
- Double counting
- Confusing split representations
- Ledger concepts leaking into bank UX

---

## Reconciliation Philosophy

- Reconciliation is an accounting task
- It applies to journal lines, not bank feed items
- If a journal line exists, it is considered cleared

This keeps reconciliation logic precise and auditable.

---

## Design Priorities (In Order)

1. **Accounting correctness over convenience**
2. **Single source of truth per responsibility**
3. **One categorization workflow**
4. **Transfers and splits as natural cases**
5. **Extensibility for future data sources**

---

## What This Design Intentionally Avoids

- Writing raw imports directly to the ledger
- Reusing Plaid-specific models for non-Plaid data
- Multiple categorization UIs
- Linking bank data to individual journal lines
- Source-specific accounting logic

---

## Summary

This architecture treats accounting as a **decision**, not a side effect of data ingestion.

By clearly separating:
- *What happened* (bank feed)
- *What it means* (ledger)

…the system remains predictable, extensible, and aligned with real-world accounting practices.

This foundation supports both current needs and future complexity without redesign.
