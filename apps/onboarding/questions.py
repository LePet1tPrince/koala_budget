"""
The onboarding question catalog.

**The question set is data.** Adding, removing or reordering a question is an edit
to ``QUESTION_CATALOG`` and nothing else: the phases a user walks, the payload the
client renders, the validation the server applies, and the chart of accounts that
comes out the far end are all derived from this list. Nothing counts questions or
names them anywhere else, so trimming the flow cannot leave a stale reference
behind.

Two rules keep that true, and `validate_catalog()` enforces both:

* a rule lives on the *option* that triggers it, never in a table keyed by
  question id, so deleting a question deletes its rules with it;
* a cross-question dependency is written as a ``question_id:option_value`` token
  in ``Grant.requires``, which is checked against the catalog -- so removing a
  question that another one depends on fails a test instead of silently turning
  that other rule into a no-op.

`catalog_version` on ``OnboardingState`` is bumped when a change would make
already-stored answers mean something different (see ``CATALOG_VERSION``).
"""

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

from .coa_rules import (
    BUSINESS,
    CREDIT_CARDS,
    FAMILY,
    INCOME,
    INVESTMENT_ACCOUNTS,
    LIVING,
    LOANS,
    OTHER_DEBT,
    PROPERTY,
    REGULAR,
    VARIABLE,
    AccountSpec,
    Grant,
)

# Bump when a change to the catalog would make previously stored answers mean
# something different -- a reused option value, a changed question id. Adding or
# removing a question does not by itself require a bump: old answers simply carry
# keys the current catalog ignores.
CATALOG_VERSION = 1

# Phases, in the order a user walks them. A phase with no questions is skipped,
# so emptying one out is a valid way to cut the flow down.
PHASE_INCOME = "income"
PHASE_HOUSEHOLD = "household"
PHASE_GOAL = "goal"

PHASE_ORDER = (PHASE_INCOME, PHASE_HOUSEHOLD, PHASE_GOAL)

PHASE_LABELS = {
    PHASE_INCOME: _("About your money"),
    PHASE_HOUSEHOLD: _("About your household"),
    PHASE_GOAL: _("Your first goal"),
}

# Answer shapes.
SINGLE = "single"
MULTI = "multi"
CURRENCY = "currency"
TEXT = "text"
GOAL = "goal"


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    # What picking this option adds to the chart of accounts.
    grant: Grant = field(default_factory=Grant)
    help_text: str = ""
    # An honest answer for someone none of the other options describe -- "none of
    # these", "something else". Every required question needs one, or a user whose
    # circumstances the catalog did not anticipate cannot get past it. Checked by
    # `validate_catalog()`.
    catch_all: bool = False


@dataclass(frozen=True)
class Question:
    id: str
    phase: str
    prompt: str
    kind: str
    options: tuple[Option, ...] = ()
    required: bool = False
    help_text: str = ""

    @property
    def option_values(self) -> set[str]:
        return {option.value for option in self.options}


# ---------------------------------------------------------------------------
# Phase A — about your money
# ---------------------------------------------------------------------------

Q_INCOME_SOURCES = Question(
    id="income_sources",
    phase=PHASE_INCOME,
    prompt=_("Where does your money come from?"),
    help_text=_("Pick everything that applies."),
    kind=MULTI,
    required=True,
    options=(
        Option(
            "employment",
            _("Employment (salary or wages)"),
            Grant(accounts=(AccountSpec(4000, "Salary Income", INCOME.name),)),
        ),
        Option(
            "self_employment",
            _("Self-employment or freelance"),
            Grant(
                groups=(BUSINESS,),
                accounts=(
                    AccountSpec(4100, "Self-Employment Income", INCOME.name),
                    AccountSpec(5600, "Business Supplies", BUSINESS.name),
                    AccountSpec(5610, "Professional Fees", BUSINESS.name),
                ),
            ),
        ),
        Option(
            "rental",
            _("Rental property"),
            Grant(
                groups=(PROPERTY, LIVING),
                accounts=(
                    AccountSpec(1300, "Rental Property", PROPERTY.name),
                    AccountSpec(4200, "Rental Income", INCOME.name),
                    AccountSpec(5010, "Property Tax", LIVING.name),
                    AccountSpec(5020, "Property Maintenance", LIVING.name),
                    AccountSpec(5030, "Property Insurance", LIVING.name),
                ),
            ),
        ),
        Option(
            "investments",
            _("Investments and dividends"),
            Grant(accounts=(AccountSpec(4300, "Dividend & Interest Income", INCOME.name),)),
        ),
        Option(
            "pension",
            _("Pension or government benefits"),
            Grant(accounts=(AccountSpec(4400, "Pension & Benefits", INCOME.name),)),
        ),
        Option(
            "other",
            _("Something else"),
            Grant(accounts=(AccountSpec(4900, "Other Income", INCOME.name),)),
            catch_all=True,
        ),
    ),
)

Q_HOUSEHOLD_SHAPE = Question(
    id="household_shape",
    phase=PHASE_INCOME,
    prompt=_("Is this just you, or you and a partner?"),
    kind=SINGLE,
    required=True,
    options=(
        Option("solo", _("Just me"), catch_all=True),
        Option(
            "partner",
            _("Me and a partner"),
            # Only meaningful alongside employment income -- a second salary account
            # would be noise for a household living on a pension.
            Grant(
                accounts=(AccountSpec(4010, "Salary Income — Partner", INCOME.name),),
                requires=("income_sources:employment",),
            ),
        ),
    ),
)

Q_MONTHLY_INCOME = Question(
    id="monthly_income",
    phase=PHASE_INCOME,
    prompt=_("Roughly how much lands in your account each month?"),
    help_text=_("A rough number is fine, and you can skip this entirely."),
    kind=CURRENCY,
    required=False,
)


# ---------------------------------------------------------------------------
# Phase B — about your household
# ---------------------------------------------------------------------------

Q_HOUSING = Question(
    id="housing",
    phase=PHASE_HOUSEHOLD,
    prompt=_("Where do you live?"),
    kind=SINGLE,
    required=True,
    options=(
        Option(
            "rent",
            _("I rent"),
            Grant(
                groups=(LIVING,),
                accounts=(
                    AccountSpec(5000, "Rent", LIVING.name),
                    AccountSpec(5040, "Tenant Insurance", LIVING.name),
                ),
            ),
        ),
        Option(
            "mortgage",
            _("I have a mortgage"),
            Grant(
                groups=(LIVING, LOANS),
                accounts=(
                    AccountSpec(2200, "Mortgage", LOANS.name),
                    AccountSpec(5000, "Mortgage Interest", LIVING.name),
                    AccountSpec(5010, "Property Tax", LIVING.name),
                    AccountSpec(5050, "Home Insurance", LIVING.name),
                    AccountSpec(5060, "Home Maintenance", LIVING.name),
                ),
            ),
        ),
        Option(
            "owned",
            _("I own my home outright"),
            Grant(
                groups=(LIVING,),
                accounts=(
                    AccountSpec(5010, "Property Tax", LIVING.name),
                    AccountSpec(5050, "Home Insurance", LIVING.name),
                    AccountSpec(5060, "Home Maintenance", LIVING.name),
                ),
            ),
        ),
        Option("other", _("With family, or something else"), catch_all=True),
    ),
)

Q_KIDS = Question(
    id="kids",
    phase=PHASE_HOUSEHOLD,
    prompt=_("Any kids at home?"),
    kind=SINGLE,
    required=True,
    options=(
        Option("no", _("No"), catch_all=True),
        Option(
            "yes",
            _("Yes"),
            Grant(
                groups=(FAMILY,),
                accounts=(
                    AccountSpec(5700, "Childcare", FAMILY.name),
                    AccountSpec(5710, "Kids' Activities", FAMILY.name),
                    AccountSpec(5720, "Education", FAMILY.name),
                ),
            ),
        ),
    ),
)

Q_TRANSPORT = Question(
    id="transport",
    phase=PHASE_HOUSEHOLD,
    prompt=_("How do you get around?"),
    kind=MULTI,
    required=True,
    options=(
        Option(
            "car_loan",
            _("A car I'm still paying off"),
            Grant(
                groups=(PROPERTY, LOANS),
                accounts=(
                    AccountSpec(1400, "Vehicle", PROPERTY.name),
                    AccountSpec(2300, "Car Loan", LOANS.name),
                    AccountSpec(5310, "Fuel", REGULAR.name),
                    AccountSpec(5320, "Car Insurance", REGULAR.name),
                    AccountSpec(5330, "Car Maintenance", REGULAR.name),
                ),
            ),
        ),
        Option(
            "car_owned",
            _("A car I own outright"),
            Grant(
                groups=(PROPERTY,),
                accounts=(
                    AccountSpec(1400, "Vehicle", PROPERTY.name),
                    AccountSpec(5310, "Fuel", REGULAR.name),
                    AccountSpec(5320, "Car Insurance", REGULAR.name),
                    AccountSpec(5330, "Car Maintenance", REGULAR.name),
                ),
            ),
        ),
        Option("transit", _("Transit"), Grant(accounts=(AccountSpec(5340, "Transit", REGULAR.name),))),
        Option("active", _("Bike or walk"), catch_all=True),
    ),
)

Q_DEBTS = Question(
    id="debts",
    phase=PHASE_HOUSEHOLD,
    prompt=_("Do you have any of these?"),
    help_text=_("Credit cards are already set up for you."),
    kind=MULTI,
    required=True,
    options=(
        Option(
            "second_credit_card",
            _("More than one credit card"),
            Grant(accounts=(AccountSpec(2010, "Credit Card 2", CREDIT_CARDS.name, has_feed=True),)),
        ),
        Option(
            "line_of_credit",
            _("Line of credit"),
            Grant(
                groups=(OTHER_DEBT,),
                accounts=(AccountSpec(2100, "Line of Credit", OTHER_DEBT.name, has_feed=True),),
            ),
        ),
        Option(
            "student_loan",
            _("Student loan"),
            Grant(
                groups=(OTHER_DEBT,),
                accounts=(
                    AccountSpec(2400, "Student Loan", OTHER_DEBT.name),
                    AccountSpec(5810, "Student Loan Interest", REGULAR.name),
                ),
            ),
        ),
        Option(
            "other_loan",
            _("Another loan"),
            Grant(groups=(OTHER_DEBT,), accounts=(AccountSpec(2500, "Other Loan", OTHER_DEBT.name),)),
        ),
        Option("none", _("None of these"), catch_all=True),
    ),
)

Q_SAVINGS = Question(
    id="savings",
    phase=PHASE_HOUSEHOLD,
    prompt=_("Where do you save or invest?"),
    kind=MULTI,
    required=True,
    options=(
        Option(
            "tfsa",
            _("TFSA"),
            Grant(groups=(INVESTMENT_ACCOUNTS,), accounts=(AccountSpec(1200, "TFSA", INVESTMENT_ACCOUNTS.name),)),
        ),
        Option(
            "rrsp",
            _("RRSP"),
            Grant(groups=(INVESTMENT_ACCOUNTS,), accounts=(AccountSpec(1210, "RRSP", INVESTMENT_ACCOUNTS.name),)),
        ),
        Option(
            "resp",
            _("RESP"),
            Grant(groups=(INVESTMENT_ACCOUNTS,), accounts=(AccountSpec(1220, "RESP", INVESTMENT_ACCOUNTS.name),)),
        ),
        Option(
            "brokerage",
            _("A non-registered or brokerage account"),
            Grant(
                groups=(INVESTMENT_ACCOUNTS,),
                accounts=(AccountSpec(1230, "Brokerage Account", INVESTMENT_ACCOUNTS.name),),
            ),
        ),
        Option("none", _("Not yet"), catch_all=True),
    ),
)

Q_EXTRAS = Question(
    id="extras",
    phase=PHASE_HOUSEHOLD,
    prompt=_("Anything else you spend on regularly?"),
    kind=MULTI,
    required=True,
    options=(
        Option("pets", _("Pets"), Grant(accounts=(AccountSpec(5510, "Pets", VARIABLE.name),))),
        Option("travel", _("Travel"), Grant(accounts=(AccountSpec(5520, "Travel", VARIABLE.name),))),
        Option("fitness", _("Fitness"), Grant(accounts=(AccountSpec(5530, "Fitness", VARIABLE.name),))),
        Option("hobbies", _("Hobbies"), Grant(accounts=(AccountSpec(5540, "Hobbies", VARIABLE.name),))),
        Option(
            "subscriptions",
            _("Subscriptions"),
            Grant(accounts=(AccountSpec(5550, "Subscriptions", VARIABLE.name),)),
        ),
        Option("charity", _("Charity"), Grant(accounts=(AccountSpec(5560, "Charity & Giving", VARIABLE.name),))),
        Option("medical", _("Medical"), Grant(accounts=(AccountSpec(5570, "Medical", REGULAR.name),))),
        Option("none", _("Nothing else for now"), catch_all=True),
    ),
)


# ---------------------------------------------------------------------------
# Phase B+ — first goal (optional)
# ---------------------------------------------------------------------------

Q_FIRST_GOAL = Question(
    id="first_goal",
    phase=PHASE_GOAL,
    prompt=_("What's the first thing you want to save for?"),
    help_text=_("You can skip this and add goals later."),
    kind=GOAL,
    required=False,
)


# The catalog. Edit this list to change the flow -- nothing else counts or names
# questions. Order within a phase is the order they are asked.
QUESTION_CATALOG: tuple[Question, ...] = (
    Q_INCOME_SOURCES,
    Q_HOUSEHOLD_SHAPE,
    Q_MONTHLY_INCOME,
    Q_HOUSING,
    Q_KIDS,
    Q_TRANSPORT,
    Q_DEBTS,
    Q_SAVINGS,
    Q_EXTRAS,
    Q_FIRST_GOAL,
)


# ---------------------------------------------------------------------------
# Derived accessors -- everything else reads the catalog through these
# ---------------------------------------------------------------------------


def questions_for_phase(phase: str) -> tuple[Question, ...]:
    return tuple(q for q in QUESTION_CATALOG if q.phase == phase)


def active_phases() -> tuple[str, ...]:
    """Phases that still have at least one question; emptying a phase skips it."""
    return tuple(phase for phase in PHASE_ORDER if questions_for_phase(phase))


def get_question(question_id: str) -> Question | None:
    return next((q for q in QUESTION_CATALOG if q.id == question_id), None)


def required_question_ids() -> tuple[str, ...]:
    return tuple(q.id for q in QUESTION_CATALOG if q.required)


def catalog_payload() -> list[dict]:
    """
    The catalog as the client needs it: prompts, options and shapes, with the
    chart-of-accounts rules left behind on the server.
    """
    return [
        {
            "id": q.id,
            "phase": q.phase,
            "prompt": str(q.prompt),
            "help_text": str(q.help_text),
            "kind": q.kind,
            "required": q.required,
            "options": [{"value": o.value, "label": str(o.label), "help_text": str(o.help_text)} for o in q.options],
        }
        for q in QUESTION_CATALOG
    ]


def validate_catalog() -> list[str]:
    """
    Return a list of problems with the catalog; empty means it is coherent.

    Called from a test rather than at import time, so a mistake surfaces as a
    named failure instead of a crash on startup.
    """
    problems: list[str] = []
    seen_ids: set[str] = set()

    for question in QUESTION_CATALOG:
        if question.id in seen_ids:
            problems.append(f"duplicate question id: {question.id}")
        seen_ids.add(question.id)

        if question.phase not in PHASE_ORDER:
            problems.append(f"{question.id}: unknown phase {question.phase!r}")

        if question.kind in (SINGLE, MULTI) and not question.options:
            problems.append(f"{question.id}: {question.kind} question has no options")

        if question.kind in (CURRENCY, TEXT, GOAL) and question.options:
            problems.append(f"{question.id}: {question.kind} question should not carry options")

        seen_values: set[str] = set()
        for option in question.options:
            if option.value in seen_values:
                problems.append(f"{question.id}: duplicate option value {option.value!r}")
            seen_values.add(option.value)

    # A required question must offer an honest answer to someone none of its
    # options describe, or the flow deadlocks for them.
    for question in QUESTION_CATALOG:
        if question.required and question.options and not any(o.catch_all for o in question.options):
            problems.append(f"{question.id}: required question has no catch-all option")

    # Cross-question dependencies must point at something that exists.
    for question in QUESTION_CATALOG:
        for option in question.options:
            for token in option.grant.requires:
                if ":" not in token:
                    problems.append(f"{question.id}:{option.value}: malformed requires token {token!r}")
                    continue
                other_id, other_value = token.split(":", 1)
                other = get_question(other_id)
                if other is None:
                    problems.append(f"{question.id}:{option.value}: requires unknown question {other_id!r}")
                elif other_value not in other.option_values:
                    problems.append(
                        f"{question.id}:{option.value}: requires unknown option {other_value!r} of {other_id!r}"
                    )

    return problems
