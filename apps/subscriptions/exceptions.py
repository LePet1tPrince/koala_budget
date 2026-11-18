class SubscriptionConfigError(Exception):
    pass


class FeatureGateError(Exception):
    pass


class NoSubscriptionFoundError(FeatureGateError):
    pass


class PlanNotSupportedError(FeatureGateError):
    pass


class PriceNotAllowedError(Exception):
    """A checkout asked for a price this team may not buy (another product, or the founding price)."""
