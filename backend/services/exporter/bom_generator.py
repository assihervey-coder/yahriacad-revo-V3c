"""Générateur BOM — CSV (Ref,Qty,Value,Footprint,MPN,Description,Price) + JSON.

Lignes regroupées par MPN (fallback value+footprint), refs concaténées.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from shared.utilities import get_logger

log = get_logger(__name__)

COLUMNS = ["Ref", "Qty", "Value", "Footprint", "MPN", "Description", "Price"]


def _group_key(comp: Any) -> tuple[str, str, str]:
    mpn = str(getattr(comp, "mpn", "") or "").strip()
    value = str(getattr(comp, "value", "") or "").strip()
    footprint = str(getattr(comp, "footprint", "") or "").strip()
    return (mpn, value, footprint)


class BOMGenerator:
    """BOM groupé par référence fabricant (MPN)."""

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def rows(self) -> list[dict[str, Any]]:
        """Lignes de BOM [{Ref, Qty, Value, Footprint, MPN, Description, Price}]."""
        groups: dict[tuple[str, str, str], list[Any]] = {}
        for ref in sorted(self.graph.components):
            groups.setdefault(_group_key(self.graph.components[ref]), []).append(
                self.graph.components[ref])
        rows: list[dict[str, Any]] = []
        for (mpn, value, footprint), comps in groups.items():
            refs = sorted(str(getattr(c, "ref", "")) for c in comps)
            price = sum(float(getattr(c, "price_usd", 0.0) or 0.0) for c in comps) / len(comps)
            rows.append({
                "Ref": " ".join(refs),
                "Qty": len(refs),
                "Value": value,
                "Footprint": footprint,
                "MPN": mpn or value or "N/A",
                "Description": f"{value} {footprint}".strip(),
                "Price": round(price, 4),
            })
        log.info("BOM: %d lignes groupées", len(rows))
        return rows

    def generate_csv(self) -> str:
        """CSV avec en-têtes : Ref,Qty,Value,Footprint,MPN,Description,Price."""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in self.rows():
            writer.writerow(row)
        return buf.getvalue()

    def generate_json(self) -> str:
        """JSON (liste de lignes, mêmes colonnes)."""
        return json.dumps(self.rows(), indent=2, ensure_ascii=False)
