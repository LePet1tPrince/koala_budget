# Multiple sets of books per team

Status: implemented (M1–M6). Decisions D1–D7 confirmed; see "Implementation notes" at the end for where the build differs from this plan. Motivated by the "Let me budget with future income"
setting (`docs/unassigned-plan.md` §2, §6), which belongs to a set of books rather
than to a team or a person.

## 1. What changes

Today the **team** is the tenant: every financial row carries `team`, every URL is
`/a/{team_slug}/…`, and every query filters by team. After this work:

| Level | Owns | Examples |
|---|---|---|
| **User** | identity | profile, API keys, AI chat history |
| **Team** | people and billing | members, roles, invitations, subscription, feature flags |
| **Book** (a set of books) | **all money data** | chart of accounts, payees, institutions, journal, budget, goals, bank feed, Plaid connections, reconciliation, monthly review, onboarding state, YNAB/portability imports, the future-income setting |

A team has one or more books. **Nothing is shared between two books**: no account,
transaction, budget or goal belongs to more than one, and no query spans two. A book
belongs to exactly one team, so there is no overlap between teams either.

In v1 every member of a team can open every book of that team, with the role they
already have on the team (admins can do admin things in every book). Per-book
permissions are an open question (§11).

## 2. Decisions

All seven are confirmed.

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | Name in code | Model **`Book`**; `request.book`, `book_slug`, `BaseBookModel`, `for_book`. The UI says "books" / "set of books". | It's the accounting term, and it's singular in code. |
| D2 | URL shape | **`/a/{team_slug}/{book_slug}/…`** for everything in a book. A book slug is unique **within its team** (`personal`, `business`). Team-level pages stay at `/a/{team_slug}/…` (D4). | The URL states the hierarchy, and book slugs stay short and readable at any number of teams or books. Team-level pages keep their current home, so Stripe return URLs and team management don't move. Cost: every book URL takes two slugs, and today's book URLs move (§4 covers the redirect). |
| D3 | `team` column on book-scoped rows | **Keep it during the migration, drop it at the end** (§8, M6). `BaseBookModel.save()` sets `team = book.team`. | While both exist, a query that hasn't been converted still filters by team. A miss can then only show another book *of the same team*, to people who can already open it, and never another team's data. Dropping it at the end leaves one source of truth. |
| D4 | Team-level pages (members, invitations, subscription, team name, team settings) | Stay at **`/a/{team_slug}/team/…`**, **`/a/{team_slug}/subscription/…`** and **`/a/{team_slug}/settings/`**. `/a/{team_slug}/` redirects to the book the user last opened. | These pages belong to the team, not to any book. It also leaves Stripe's return URLs and the dj-stripe `request.team` callback untouched. |
| D5 | Future-income setting | `Book.budget_future_income`. Existing books: **on** (today's behaviour). New books: asked in onboarding, default **off**. | Set per book, and the defaults leave every existing budget unchanged. |
| D6 | Plaid | A bank connection belongs to exactly one book. | `plaid_item_id` and `plaid_account_id` are globally unique, and feed accounts map to one chart of accounts. Connecting the same bank to two books means two connections. |
| D7 | Billing | Subscription stays on the team. Whether plans cap the number of books is open (§11). | Nothing in the app is subscription-gated today. |

## 3. Data model

```python
class Book(BaseModel):
    """A set of books: one tenant's chart of accounts, budget and transactions."""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="books")
    name = models.CharField(max_length=100)
    slug = models.SlugField()                     # unique within the team; second URL segment
    budget_future_income = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = [("team", "name"), ("team", "slug")]
        ordering = ["sort_order", "name"]


class BaseBookModel(BaseModel):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)   # transitional, dropped in M6

    objects = models.Manager()
    for_book = BookScopedManager()                 # filters by the current-book context var

    def save(self, *args, **kwargs):
        self.team_id = self.book.team_id           # the two can never disagree
        super().save(*args, **kwargs)
```

Bulk paths (`bulk_create` in the YNAB importer and portability apply) bypass `save()`
and must set both columns; a test asserts no row has `team_id != book.team_id`.

**Slugs.** A book slug is derived from its name when the book is created
(`slugify(name)`, suffixed `-2`, `-3`… on a clash within the team). Renaming a book
does not change its slug, so links survive a rename. The slug can be edited separately
in book settings, with a warning that old links will stop working.

The data migration names each team's default book **"Personal"** with slug
`personal`. A new team's first book gets the same name and slug; onboarding offers to
rename it.

**Reserved slugs.** Team-level pages share the `/a/{team_slug}/` prefix with books (D4),
so a book slug may not equal a team-level segment (`team`, `subscription`, `settings`).
It also may not equal a book-level app prefix (`accounts`, `journal`, `budget`,
`reports`, `bankfeed`, `plaid`, `onboarding`, `ynab-import`, `data`, `reconcile`,
`audit`). The second set is what lets the legacy-URL redirect (§4) tell an old
`/a/{team}/budget/` from a book called "budget". The reserved list is derived from
the URLconf rather than hand-written, and a test fails if a new prefix is added
without being reserved.

**The 19 models that move to `BaseBookModel`**, with their uniqueness rewritten from
team to book:

| App | Models | Constraint changes |
|---|---|---|
| accounts | AccountGroup, Account, Institution, Payee | `(team, name)` → `(book, name)` on AccountGroup, Institution, Payee |
| journal | JournalEntry, JournalLine | — (`JournalLine._calculate_budget` filters Budget by team → book) |
| budget | Budget, Goal, GoalAllocation | `(team, month, category)`, `(team, name)`, `(team, goal, month)` → book |
| bank_feed | BankTransaction, TransferMatchDismissal | `(team, low, high)` → book; `TransferMatchDismissal.record(team, …)` → book |
| plaid | PlaidItem, PlaidAccount, PlaidTransaction | — (global Plaid ids stay unique) |
| reconciliation | Reconciliation | — (keyed on account) |
| monthly_review | MonthlyReviewState | `(team, month)` → `(book, month)` |
| onboarding | OnboardingState | `unique_together = ["team"]` → `["book"]` — each book is onboarded on its own |
| portability | DataImport | — |
| ynab_import | YnabImport | — |

Not moving: `teams_example.Player` (demo), `Membership`, `Invitation`, `Flag`.
`audit.AuditEvent` and `AuditLog` gain a nullable `book` FK beside their nullable
`team` (login/logout events have a team context but no book).

## 4. Request plumbing

- **URLs.** Two includes under the team prefix, with team-level patterns first so
  they win over a book slug:

  ```python
  path("a/<slug:team_slug>/", include(team_level_urlpatterns)),  # "", team/, subscription/, settings/
  path("a/<slug:team_slug>/<slug:book_slug>/", include(book_urlpatterns)),  # accounts/, journal/, budget/, ...
  ```

  The ~109 book views gain a `book_slug` parameter (codemod). The team-level views in
  `apps.teams`, `apps.subscriptions` and the Settings hub keep their signatures.
- **Reversing.** Every book URL takes both slugs, for 87 `reverse()` calls, 141
  template `{% url %}` tags and the `get_absolute_url` methods. One helper,
  `Book.url_args` (returns `(team.slug, book.slug)`), and `request.book` in templates
  keep call sites short: `{% url 'budget:budget_home' request.team.slug request.book.slug %}`.
- **Legacy redirect.** Today's URLs are `/a/{team}/budget/…`. A small view mounted
  after the book include catches `/a/{team}/{prefix}/{rest}` when `prefix` is a
  book-level app prefix. It **301-redirects** to the same path under the team's
  default book (`/a/{team}/personal/budget/…`), keeping the query string. Bookmarks,
  emailed links and old onboarding and monthly-review links keep working. The
  reserved-slug rule (§3) makes this unambiguous. Only GETs are redirected; a POST to
  an old URL gets a 404, which in practice means an open tab from before the deploy.
- **Middleware** (`apps/teams/middleware.py`, or a new `apps/books` app):
  - `request.team`: from `team_slug`, exactly as today. It keeps its meaning, so
    `login_and_team_required`, `team_admin_required`, `TeamAccessPermissions`,
    `request.team_membership`, dj-stripe's request callback and waffle's `Flag` keep
    working without edits.
  - `request.book`: from `book_slug`, looked up **within** `request.team`
    (`Book.objects.get(team=request.team, slug=book_slug)`). A book of another team
    is a 404 even to someone who belongs to both teams. `None` on team-level pages.
  - `request.default_book`: the book in `session["book"]` if it still belongs to one
    of the user's teams, else the first book of the default team. It drives the nav
    on team-level and account pages (`get_nav_team` gains a `get_nav_book` sibling)
    and the `/a/{team}/` redirect.
  - A `current_book` context var beside `current_team`, set and unset the same way
    and tagged in Sentry.
- **Access.** A user may open a book iff they are a member of `book.team`. Because
  the team comes from the URL and the book is looked up inside it, the existing
  decorators already enforce this; a `login_and_book_required` variant adds only
  "404 if there is no `request.book`". A new `BookModelAccessPermissions` checks
  `obj.book_id == request.book.id` and replaces `TeamModelAccessPermissions` on the
  book-scoped viewsets.
- **Context processors.** `nav_book` joins `nav_team`. `inbox_count`,
  `nav_feed_accounts`, `unassigned_pill` and `onboarding_rail` filter by book and
  render nothing on team-level pages without a nav book.
- **Outside requests.**
  - `sync_plaid_transactions` derives the book from the item and sets and unsets
    `current_book`. Today it sets the team context and never unsets it; that gets
    fixed in passing.
  - Portability and YNAB tasks read `record.book`.
  - `log_event` gains `book=`, falling back to `request.book`.
  - Externally registered URLs are reviewed: Plaid's OAuth redirect URI and any
    email templates. Stripe's are team-level and unaffected (D4).
- **Frontend.**
  - The views emit one `book-base` value (`/a/{team}/{book}/`) via `json_script`,
    replacing `team-slug`.
  - The four JS files that hardcode `/a/${teamSlug}/` URLs (`bank_feed.js`,
    `CategorizeMode.jsx`, `LineApp.jsx`, `TransactionHistory.jsx`) build from it, so
    a future URL change is a one-place edit.
  - The api-client is regenerated. Its paths gain a `{book_slug}` parameter beside
    `{team_slug}`; `getApiConfiguration` supplies both from the page.

## 5. The query sweep

Every filter on book data changes from team to book, and every service that takes a
team takes a book instead (`BudgetService`, `GoalService`, `NetWorthService`,
`ReportService`, `compute_unassigned`, `build_review`, `apply_template`,
`find_transfer_candidates`, `build_history_index`, the journal filter functions, the
onboarding gate and opening-balance functions, the portability and YNAB services).

Measured scope in non-test code (team filters / `request.team` / `for_team` /
`self.team`): bank_feed ~120, budget ~120, portability ~80, accounts ~60,
reconciliation ~45, onboarding ~35, reports ~45, ynab_import ~35, monthly_review ~27,
journal ~28, plaid ~17, audit ~13, web ~11. Tests carry ~1,900 more lines, mostly
fixtures, which move to a `book` fixture.

Converted app by app, in dependency order — accounts → journal → budget → bank_feed →
plaid → reconciliation → reports → monthly_review → onboarding → ynab_import →
portability → web (dashboard) → audit → users (data export) — each with its own
cross-book isolation tests (§9) before moving on.

**Places that need more than a find-and-replace:**

- **`portability/services/wipe.py::wipe_team`** raw-deletes journal lines and entries
  (`_raw_delete`, no signals) and then accounts, groups, payees and Plaid rows by
  team. Left alone, "import into book B" would **erase every book in the team**.
  It becomes `wipe_book(book)` and gets its own test with two populated books.
- **`users/services.py`** (the user data export) loops over a user's teams; it must
  loop over each team's books.
- **`JournalLine._calculate_budget`** and **`Goal.save()`** (which creates the
  "Goals" group and backing account) scope by team inside model code.
- **`AccountTeamScopedManager`** duplicates `TeamScopedManager`; both are replaced by
  one `BookScopedManager`.
- **`apply_template`** uses `get_or_create` keyed on team + name, so a second book
  would silently reuse the first book's accounts.
- **Onboarding**: `team_home` redirects an un-onboarded *team*; it becomes the book
  home redirecting an un-onboarded *book*.

## 6. The future-income setting

`Book.budget_future_income`, edited under **Settings → This set of books → Budgeting**.

- **On** (existing books): exactly today's behaviour. Income is budgeted, and this
  month's budgeted-but-not-received income counts toward Unassigned.
- **Off**:
  - `compute_unassigned` sets `income_due = 0`, so money is unassigned only once it
    has landed.
  - The budget page hides the Income section, the grid hides income rows, and
    Budget vs Actual hides its income section. The income-account budget chart on
    the activity pages is hidden too.
  - `budget_save_amount`, `budget_grid_save` and autofill/auto-assign **refuse**
    income categories server-side, not just in the UI.
  - Onboarding and the YNAB importer skip creating income budgets.
  - Existing income `Budget` rows are kept and ignored, so switching back restores
    them.
- **The toggle shows its consequence** before saving: "Your Unassigned would be $X
  instead of $Y this month". Computed server-side with the flag flipped, so it can't
  disagree with the page.
- **New books** answer it in onboarding ("Do you budget your paycheque before it
  arrives?"), defaulting to off.

This milestone can ship **before** the query sweep: once M1 exists every team has
exactly one book, so a book-level setting behaves as a team-level one until a team
creates its second book.

## 7. UI

- **Switcher.** The sidebar team tile becomes *Team › Book* with the book name as
  the main label. Its menu lists this team's books (current one ticked), then other
  teams (each opening its most recent book), then "New set of books" and team
  settings. The mobile menu mirrors it.
- **Creating a book.** Name → then one of: the onboarding questionnaire (per-book
  `OnboardingState`), "Coming from YNAB?" (the existing wizard, into the new book),
  or "Load an export" (portability into the new, empty book). "Copy the chart of
  accounts from <book>" is a cheap later addition.
- **Settings hub.** One rail, two groups, split across the two URL levels:
  - **This set of books**, under `/a/{team}/{book}/settings/…`: name and slug,
    Budgeting (the future-income toggle), Export & Import, Import from YNAB, Audit
    log, and Archive/Delete (admin only, type the name to confirm, refused for the
    team's last book).
  - **Team**, under `/a/{team}/settings/`, `/team/`, `/subscription/` (unchanged):
    team details, members and invitations, subscription. While on a team page, the
    rail links "This set of books" to the nav book.
  - Account-level sections (profile, password) stay as they are.
- **Wording.** Page titles and the dashboard greeting name the book when a team has
  more than one; nothing changes for a single-book team.

## 8. Milestones

Each milestone ships with the full test suite green.

1. **M1 Foundation.**
   - `Book` model, plus a data migration creating one book per team (name
     "Personal", slug `personal`, `budget_future_income = True`).
   - URLs split into team-level and book-level includes (§4). Book views take
     `book_slug`, every book URL is reversed with both slugs, and the frontend
     builds from `book-base`. The api-client is regenerated.
   - The legacy redirect goes live the same day, so no existing link breaks.
   - New teams get a default book (signal on Team create, beside
     `bootstrap_team_on_create`).
   - No financial query changes yet; the book only exists in URLs and on
     `request.book`.
2. **M2 Future-income setting** (§6) on `Book`, with its Settings page. Ships to users
   here.
3. **M3 Book column on every row.**
   - Add a nullable `book` FK to the 19 models, backfill each row with its team's
     default book, then make it non-null.
   - `BaseBookModel.save()` keeps `team` in step.
   - Add the book-keyed unique constraints next to the team-keyed ones.
4. **M4 Query sweep** (§5) app by app, with the isolation suite (§9) growing as each
   app lands. The team-keyed constraints are dropped per app once it is converted.
5. **M5 Multiple books.**
   - Switcher, create, rename, archive/delete, per-book onboarding and the book home.
   - The "New set of books" entry stays behind a waffle flag until M4 is complete;
     until then a second book would show a half-converted app.
6. **M6 Cleanup.**
   - Drop `team` from the 19 models and remove `TeamScopedManager`,
     `AccountTeamScopedManager` and `for_team`.
   - Replace `STRICT_TEAM_CONTEXT` with `STRICT_BOOK_CONTEXT`.
   - Rename the leftover `team_*` identifiers.

## 9. Testing

- **Cross-book isolation suite** (new, the backbone of M4). Two books in one team,
  each with a full set of data.
  - Every list page and API for book A shows none of book B's rows.
  - Every object URL requested with book B's pk under book A's slug returns 404.
  - Every write under A leaves B untouched, checked by row counts and checksums on B.
  - Parameterized over URL names, so a new endpoint fails the suite until it is
    covered.
- **Cross-team check.** A member of team X gets 404 for every book of team Y, as today.
- **Structural tests**, in the same style as `test_icons.py`/`test_schema.py`:
  - every concrete `BaseBookModel` has `team_id == book.team_id` after the bulk import
    paths run;
  - after M6, no model under `apps/` subclasses `BaseTeamModel` except the demo;
  - a scan fails on `filter(team=` against a model in the book list.
- **Migrations.** The M1 data migration (one book per team, slug equal to the team's)
  and the M3 backfill (every row's book is its team's default book) each get a test.
- **E2E.**
  - The `team` fixture also creates the default book and marks it onboarded.
  - New `second_book` fixture.
  - Tests for switching books, creating a book through onboarding, and the
    future-income toggle hiding and restoring the Income section.
  - Page objects take the book slug as well as the team slug (41 `/a/` paths across
    18 e2e files). A legacy-redirect test visits an old `/a/{team}/budget/` URL and
    lands on the default book.

## 10. Risks

| Risk | Mitigation |
|---|---|
| A missed filter shows another book's data | D3: the team column stays until M6, so a miss is contained within one team. The isolation suite catches it. |
| `wipe_team` erases sibling books | Converted and tested first in the portability step. |
| Old `/a/{team}/…` links break when URLs move | The legacy 301 redirect (§4) ships in the same deploy as the URL change, with a test per book-level app prefix. |
| A book slug shadows a team-level page or an old URL | The reserved-slug list is derived from the URLconf, and a test fails if a new prefix isn't reserved. |
| Missing the second slug at a `reverse()` / `{% url %}` call site | Django raises `NoReverseMatch` loudly, and the full suite plus the e2e run cover every page. `Book.url_args` keeps call sites short. |
| api-client drift | Regenerated in M1 and checked by the existing schema test. |
| Performance | The book FK is indexed. Team indexes are dropped with the column in M6. The pill and context processors do the same work, keyed differently. |

## 11. Open questions

- **Per-book permissions.** Should a member be limited to some books (e.g. a
  bookkeeper who sees only the business books)? v1 says no.
- **Billing.** Do plans cap the number of books?
- **AI chat.** It is user-scoped with no finance tools today. When finance tools
  arrive, they should act on the current book, and chats should probably become
  per-book.
- **Moving data between books.** Out of scope for v1. Export → import into a new
  book covers "split this off" coarsely.
- **UI wording.** "books" vs "set of books" in labels and headings. The code name is
  settled (`Book`, D1).

## 12. Implementation notes

Built in one change covering M1–M6. Where it differs from the text above:

- **Milestones were not shipped separately.** The code went straight to the M6 end
  state (no `team` column on book models). The migrations still follow M1 → M3 → M6
  as separate steps (`books.0001`–`0003`, each app's `00NN_book` and
  `00NN_book_required`), and they are reversible: the required step makes `team`
  nullable before dropping it and refills it from the book on the way back.
- **No waffle flag for "New set of books".** It was only there to hide a
  half-converted app until M4 landed; M4 landed in the same change.
- **`BaseTeamModel`, `TeamScopedManager` and `STRICT_TEAM_CONTEXT` remain** for the
  Pegasus `teams_example.Player` demo only (§9's structural test expects exactly
  that). `AccountTeamScopedManager` and `for_team` on financial models are gone.
- **The legacy redirect is mounted before the book include**, not after: with the
  book include first, `/a/{team}/budget/` resolves as a book called `budget` and a
  later pattern never runs. The reserved-slug rule makes the order safe.
- **Team-level `books/`** (`/a/{team}/books/`, list and create) was added; the slug is
  reserved like every other first segment.
- **Book settings are admin-only** (name/slug, budgeting, archive/delete) and so is
  creating a book. Archived books stay reachable by URL (so they can be restored)
  but leave the switcher and are never a default.
- **Export & Import confirms with the book's name**, not the team's: it is the book
  that gets replaced. Its manifest `source` carries both names.
- **Loading an export finishes the book's onboarding**, as the YNAB import already
  did, so a book started that way does not land in the questionnaire.
- **The api-client was patched, not regenerated** (no Java/generator available in
  the build environment); the patch follows the generator's own output shape.
  `make build-api-client` should produce the same result.
- **Found by the isolation suite and fixed:** `PlaidTransactionViewSet` always
  returned a 500 (`select_related("journal_entry")`), `JournalEntrySerializer`
  accepted another tenant's account and payee ids, and another book's account on
  the activity page rendered an empty page instead of a 404.
