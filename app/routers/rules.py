from fastapi import APIRouter

from app.rules.catalog import RULES
from app.rules.engine import RULES_VERSION

router = APIRouter(tags=["rules"])


@router.get("/rules")
async def list_rules() -> dict:
    """Every rule the service applies, with its legal reference."""
    return {
        "rules_version": RULES_VERSION,
        "rules": [
            {"rule_id": rule_id, "title": info.title, "legal_ref": info.legal_ref}
            for rule_id, info in RULES.items()
        ],
    }
