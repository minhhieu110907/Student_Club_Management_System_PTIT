"""Import all model modules so the shared metadata is complete."""

from app.db.base import Base
from app.modules.ai import models as ai_models
from app.modules.audit import models as audit_models
from app.modules.clubs import models as club_models
from app.modules.events import models as event_models
from app.modules.identity import models as identity_models
from app.modules.notifications import models as notification_models
from app.modules.reliable_delivery import models as reliable_delivery_models
from app.modules.tasks import models as task_models

__all__ = ["Base"]

_MODEL_MODULES = (
    ai_models,
    audit_models,
    club_models,
    event_models,
    identity_models,
    notification_models,
    reliable_delivery_models,
    task_models,
)
