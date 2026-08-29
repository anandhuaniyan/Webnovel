from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import CompletenessStatus, MonetizationStatus
from app.models import Novel


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str


class MonetizationService:
    def novel_eligibility(self, novel: Novel) -> tuple[bool, str]:
        if not novel.published or novel.completeness_status != CompletenessStatus.COMPLETE.value:
            return False, MonetizationStatus.DISABLED.value
        if not novel.ads_eligible:
            return False, novel.monetization_status
        if novel.total_words < 5_000 or not novel.description or novel.quality_score < 70:
            return False, MonetizationStatus.LOW_VALUE.value
        return True, MonetizationStatus.ELIGIBLE.value

    def readiness_report(self, db: Session) -> dict:
        settings = get_settings()
        required_pages = [
            "privacy",
            "terms",
            "cookies",
            "about",
            "contact",
            "copyright",
            "takedown",
            "accessibility",
        ]
        checks = [
            ReadinessCheck(
                "domain",
                "WARNING" if "localhost" in settings.public_base_url else "READY",
                settings.public_base_url,
            ),
            ReadinessCheck(
                "https",
                "WARNING" if not settings.public_base_url.startswith("https://") else "READY",
                "HTTPS is required in production",
            ),
            ReadinessCheck(
                "publisher_configuration",
                "READY" if settings.adsense_client_id else "BLOCKER",
                "AdSense client ID is not configured" if not settings.adsense_client_id else "Configured",
            ),
            ReadinessCheck(
                "ads_disabled_in_development",
                "READY" if not settings.adsense_enabled else "WARNING",
                f"ADSENSE_ENABLED={settings.adsense_enabled}",
            ),
            ReadinessCheck(
                "analytics",
                "READY" if settings.ga_measurement_id else "WARNING",
                "GA measurement ID is optional until production",
            ),
            ReadinessCheck(
                "cmp",
                "WARNING" if settings.consent_provider == "local" else "READY",
                f"Provider: {settings.consent_provider}",
            ),
            ReadinessCheck("sitemap", "READY", "/sitemap.xml"),
            ReadinessCheck("robots", "READY", "/robots.txt"),
            ReadinessCheck(
                "ads_txt",
                "READY" if settings.adsense_publisher_id else "WARNING",
                "/ads.txt remains empty until a publisher ID is configured",
            ),
            ReadinessCheck("policy_pages", "READY", ", ".join(required_pages)),
        ]
        eligible = (
            db.scalar(
                select(func.count(Novel.id)).where(
                    Novel.published.is_(True),
                    Novel.ads_eligible.is_(True),
                    Novel.monetization_status == MonetizationStatus.ELIGIBLE.value,
                )
            )
            or 0
        )
        checks.append(
            ReadinessCheck(
                "eligible_content", "READY" if eligible else "BLOCKER", f"{eligible} eligible novels"
            )
        )
        overall = (
            "BLOCKERS"
            if any(check.status == "BLOCKER" for check in checks)
            else "WARNINGS"
            if any(check.status == "WARNING" for check in checks)
            else "READY"
        )
        return {"status": overall, "checks": [asdict(check) for check in checks]}
