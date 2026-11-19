"""
Request and response shapes of the onboarding API (`/a/{team}/{book}/onboarding/api/...`).

Answers and chart-of-accounts edits are read defensively by the services
(`services.answers.clean_answers`, `services.review.parse_edits`): an answer for a
question the catalog does not know is dropped, and a malformed edit list reads as
no edits. So their fields here are JSON, documented with the shape the client
sends, rather than validated a second time.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY

from .models import OnboardingState
from .questions import CURRENCY, GOAL, MULTI, SINGLE, TEXT
from .services.gates import AVAILABLE, DONE, LOCKED

# Choice sets, named in `SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]` so the generated
# client's enums say whose they are.
QUESTION_KINDS = [SINGLE, MULTI, CURRENCY, TEXT, GOAL]
PHASES = [value for value, _label in OnboardingState.PHASE_CHOICES]
TASK_STATES = [LOCKED, AVAILABLE, DONE]
TASK_ACTIONS = ["resume", "dismiss"]
OPENING_ACCOUNT_TYPES = [ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY]

# --- the catalog -------------------------------------------------------------------


class OnboardingQuestionOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    help_text = serializers.CharField(allow_blank=True)
    catch_all = serializers.BooleanField(
        help_text="“None of these”: picking it clears the other selections, and picking another clears it."
    )


class OnboardingQuestionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The key its answer is stored under.")
    phase = serializers.CharField(help_text="The phase (`phases[].key`) it is asked in.")
    prompt = serializers.CharField()
    help_text = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=QUESTION_KINDS)
    required = serializers.BooleanField()
    options = OnboardingQuestionOptionSerializer(
        many=True, help_text="Empty for free-text, currency and goal questions."
    )


class OnboardingPhaseSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class OnboardingCatalogSerializer(serializers.Serializer):
    version = serializers.IntegerField(help_text="Answers are interpreted against this catalog version.")
    phases = OnboardingPhaseSerializer(many=True, help_text="The questionnaire's phases, in order.")
    questions = OnboardingQuestionSerializer(many=True, help_text="Every question, in the order it is asked.")


# --- state -------------------------------------------------------------------------


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {},
        "description": (
            "Answers keyed by question id: an option value or a list of them for a choice question, "
            "a string or number for free text and currency, `{name, target_amount, target_date}` for a goal."
        ),
    }
)
class AnswersField(serializers.JSONField):
    default_error_messages = {"invalid": "Expected an object keyed by question id."}

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            self.fail("invalid")
        return data


class OnboardingStateSerializer(serializers.Serializer):
    phase = serializers.ChoiceField(choices=PHASES)
    question_phase = serializers.CharField(
        allow_blank=True, help_text="The questionnaire phase the user is on, while `phase` is `questions`."
    )
    answers = AnswersField()
    is_finished = serializers.BooleanField(help_text="Past the questionnaire, completed or skipped.")
    shows_tasks = serializers.BooleanField(help_text="The guided task rail belongs on this book's pages.")


class OnboardingPageSerializer(serializers.Serializer):
    """What the takeover needs to open: the state, and who it is greeting."""

    state = OnboardingStateSerializer()
    unanswered_required = serializers.ListField(
        child=serializers.CharField(), help_text="Ids of required questions still unanswered."
    )
    team_name = serializers.CharField()
    book_name = serializers.CharField()
    first_name = serializers.CharField(allow_blank=True, help_text="The signed-in user's, for the greeting.")
    ynab_import_enabled = serializers.BooleanField(help_text="Offer “Coming from YNAB?” (the YNAB import page).")


class OnboardingAnswersRequestSerializer(serializers.Serializer):
    answers = AnswersField(required=False, default=dict, help_text="Merged into the answers saved so far.")
    question_phase = serializers.CharField(
        required=False, allow_blank=True, help_text="The phase the user is moving to; unknown phases are ignored."
    )


class OnboardingAnswersResponseSerializer(serializers.Serializer):
    state = OnboardingStateSerializer()
    unanswered_required = serializers.ListField(child=serializers.CharField())


class OnboardingStateResponseSerializer(serializers.Serializer):
    state = OnboardingStateSerializer()


# --- chart of accounts review ------------------------------------------------------


class CoaAddedAccountSerializer(serializers.Serializer):
    group = serializers.CharField(help_text="A group of the generated chart.")
    name = serializers.CharField()


class CoaEditsSerializer(serializers.Serializer):
    removed = serializers.ListField(child=serializers.CharField(), help_text="Generated account names to leave out.")
    renamed = serializers.DictField(child=serializers.CharField(), help_text="Generated name → new name.")
    added = CoaAddedAccountSerializer(many=True)


@extend_schema_field(CoaEditsSerializer)
class EditsField(serializers.JSONField):
    """Documented as `CoaEdits`; read by `parse_edits`, which treats anything malformed as no edits."""


class CoaRequestSerializer(serializers.Serializer):
    """Answers (merged into the saved ones for this request) and the user's edits to the generated chart."""

    answers = AnswersField(required=False, default=dict, help_text="Merged into the saved answers, not saved.")
    edits = EditsField(required=False, default=dict)


class CoaGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    accounts = serializers.ListField(child=serializers.CharField(), help_text="Account names.")


class CoaSectionSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="The account type: asset, liability, income or expense.")
    label = serializers.CharField()
    blurb = serializers.CharField()
    groups = CoaGroupSerializer(many=True)
    count = serializers.IntegerField(help_text="Accounts in the section.")


class CoaPreviewSerializer(serializers.Serializer):
    sections = CoaSectionSerializer(many=True)


class OnboardingCompleteResponseSerializer(OnboardingStateResponseSerializer):
    """The finished state. The web client goes to the book's home next."""


# --- guided tasks ------------------------------------------------------------------


class OnboardingTaskSerializer(serializers.Serializer):
    slug = serializers.CharField()
    label = serializers.CharField()
    blurb = serializers.CharField(allow_blank=True)
    state = serializers.ChoiceField(choices=TASK_STATES)
    reason = serializers.CharField(allow_blank=True, help_text="Why a locked task is locked.")
    url = serializers.CharField(help_text="The page the task is done on.")
    anchor = serializers.CharField(allow_blank=True, help_text="A CSS selector the web coach mark points at.")
    auto = serializers.BooleanField(help_text="Completion is detected from the data; false = reported by the client.")
    dialog = serializers.CharField(allow_blank=True, help_text="A dialog the rail opens instead of navigating.")


class OnboardingTasksSerializer(serializers.Serializer):
    tasks = OnboardingTaskSerializer(many=True)
    active = serializers.BooleanField(help_text="The rail is on (the walkthrough is in its task phase).")


class OnboardingTaskRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=TASK_ACTIONS,
        required=False,
        help_text="`resume` puts the rail back; `dismiss` ends the walkthrough. Omit to report `slug` done.",
    )
    slug = serializers.CharField(required=False, help_text="A task the server cannot detect, reported done.")

    def validate(self, attrs):
        if not attrs.get("action") and not attrs.get("slug"):
            raise serializers.ValidationError({"slug": ["Name a task, or an action."]})
        return attrs


class OnboardingFinishSummarySerializer(serializers.Serializer):
    accounts = serializers.IntegerField()
    transactions = serializers.IntegerField()
    net_worth = serializers.DecimalField(max_digits=15, decimal_places=2)


class OnboardingTaskResponseSerializer(OnboardingTasksSerializer):
    finished = serializers.BooleanField(help_text="This request finished the walkthrough.")
    summary = OnboardingFinishSummarySerializer(allow_null=True, help_text="What the user built; only when `finished`.")


# --- opening balances --------------------------------------------------------------


class OpeningBalanceAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    group = serializers.CharField()
    type = serializers.ChoiceField(choices=OPENING_ACCOUNT_TYPES)
    has_opening_balance = serializers.BooleanField(help_text="Already set; a second one would double it.")


class OpeningBalancesSerializer(serializers.Serializer):
    allowed = serializers.BooleanField(help_text="False until something has been categorized.")
    reason = serializers.CharField(allow_blank=True, help_text="Why not, while not allowed.")
    net_worth = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    accounts = OpeningBalanceAccountSerializer(many=True)


class OpeningBalanceRowSerializer(serializers.Serializer):
    account_id = serializers.IntegerField()
    amount = serializers.CharField(
        allow_blank=True, help_text="What is had or owed, positive; blank skips the account."
    )


class OpeningBalancesRequestSerializer(serializers.Serializer):
    rows = OpeningBalanceRowSerializer(many=True)
    as_of = serializers.DateField(required=False, allow_null=True, help_text="Defaults to the first of this month.")


class OpeningBalancesResultSerializer(serializers.Serializer):
    net_worth_before = serializers.DecimalField(max_digits=15, decimal_places=2)
    net_worth = serializers.DecimalField(max_digits=15, decimal_places=2)
    created = serializers.IntegerField(help_text="Opening-balance entries written.")
