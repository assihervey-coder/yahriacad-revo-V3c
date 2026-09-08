"""verification/ — CERVEAU PHYSIQUE : ERC, DRC, DFM, vérification physique, scoring.

Utilisé par le validator_agent, le self_verifier (ai_engine), l'API et
le Human Surgical Editor. Aucune « estimation à la main » : les règles
viennent de DesignRules / profils usine, les résultats sont reproductibles.
"""
from services.verification.design_rules import DesignRules
from services.verification.manufacturing_rules import ManufacturingRules
from services.verification.erc_engine import ERCEngine, ERCReport, ERCViolation
from services.verification.drc_engine import DRCEngine, DRCReport, DRCViolation
from services.verification.dfm_engine import DFMEngine, DFMReport, DFMViolation
from services.verification.physical_verification import (
    PhysicalVerification,
    PhysicalVerificationReport,
)
from services.verification.quality_scoring import QualityScorer, QualityScore

__all__ = [
    "DesignRules", "ManufacturingRules",
    "ERCEngine", "ERCReport", "ERCViolation",
    "DRCEngine", "DRCReport", "DRCViolation",
    "DFMEngine", "DFMReport", "DFMViolation",
    "PhysicalVerification", "PhysicalVerificationReport",
    "QualityScorer", "QualityScore",
]
