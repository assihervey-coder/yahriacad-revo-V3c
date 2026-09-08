"""Tests unitaires — DesignVersioning (commits, restore, branches, diff).

Historique type git du DesignGraph : snapshots complets to_dict()/from_dict().
"""
from __future__ import annotations

import pytest

from services.design_core import DesignGraph, DesignVersioning


def _graphe(refs: int = 2) -> DesignGraph:
    g = DesignGraph(project_id="ver-test", name="t", board_size=(50, 40))
    for i in range(refs):
        g.add_component(f"R{i + 1}", footprint="0603", x=10.0 * (i + 1), y=10.0, placed=True)
    return g


class TestCommits:
    def test_commit_1_et_2(self) -> None:
        v = DesignVersioning("ver-test")
        r1 = v.commit(_graphe(), "init")
        assert r1.rev == 1 and r1.parent_rev is None
        r2 = v.commit(_graphe(3), "3e composant")
        assert r2.rev == 2 and r2.parent_rev == 1
        assert v.current() is r2
        assert [r.rev for r in v.list()] == [1, 2]

    def test_get_inconnu_leve_keyerror(self) -> None:
        v = DesignVersioning("ver-test")
        with pytest.raises(KeyError):
            v.get(42)


class TestRestore:
    def test_restore_rev_1_apres_modification(self) -> None:
        v = DesignVersioning("ver-test")
        v.commit(_graphe(), "init")
        v.commit(_graphe(3), "3e composant")

        restaure = v.restore(1)
        assert isinstance(restaure, DesignGraph)
        assert len(restaure.components) == 2     # état initial revenu
        assert restaure.stats()["components"] == 2


class TestBranches:
    def test_branch_checkout_commit(self) -> None:
        v = DesignVersioning("ver-test")
        v.commit(_graphe(), "init")
        v.commit(_graphe(3), "r2")

        branche = v.branch("experiment", from_rev=1)
        assert branche.head_rev == 1
        v.checkout("experiment")
        r3 = v.commit(_graphe(4), "essai sur branche")
        assert r3.rev == 3                        # compteur global
        assert v.branches()["experiment"].head_rev == 3
        # main inchangée
        v.checkout("main")
        assert v.current().rev == 2

    def test_branche_double_leve_erreur(self) -> None:
        v = DesignVersioning("ver-test")
        v.commit(_graphe(), "init")
        v.branch("dev")
        with pytest.raises(ValueError):
            v.branch("dev")


class TestDiff:
    def test_diff_composants_ajoutes_et_deplaces(self) -> None:
        v = DesignVersioning("ver-test")
        v.commit(_graphe(), "init")

        g = _graphe(3)
        g.place("R1", 25.0, 25.0)                 # déplacé
        v.commit(g, "ajout + déplacement")

        d = v.diff(1, 2)
        assert d["components_added"] == ["R3"]
        assert "R1" in d["components_moved"]
        assert d["components_moved"]["R1"]["to"] == [25.0, 25.0]
