from dataclasses import dataclass
from enum import StrEnum

from apps.users.models import CustomUser


class AgentTypes(StrEnum):
    WEATHER = "weather"
    ADMIN = "admin"


@dataclass
class UserDependencies:
    user: CustomUser
