"""The claim bank against a case whose refs the package does not know: the sandbox's demo world, or
a hidden case with new IDs. A known part keeps its package-backed arguments (drivers, forecast,
should-cost); the unknown refs are cited without a figure."""

from pathlib import Path

import pytest
from arena_kit.data import DataPackage
from arena_kit.sim import load_cases

from buyer.claims import ClaimBank

PACKAGE = Path(__file__).parent.parent / "data" / "package"


@pytest.fixture(scope="module")
def pkg():
    if not PACKAGE.exists():
        pytest.skip("no data package (uv run arena data)")
    return DataPackage(str(PACKAGE))


HIGH = 1e9  # a quote far above any recorded figure: every argument pushes our way


def supplier(case):
    s = case["suppliers"][0]
    return s["supplier_id"] if isinstance(s, dict) else s


def kinds(bank, case):
    return {c["kind"] for c in bank.for_supplier(supplier(case), HIGH)}


def test_unknown_refs_keep_package_arguments_for_a_known_part(pkg):
    case = next(c for c in load_cases().values() if c.get("refs"))
    known = kinds(ClaimBank(pkg, case), case)
    foreign = {**case, "refs": ["sc:NEW-1@2026Q3", "po:4500009999", "cost:part:NEW"]}
    got = kinds(ClaimBank(pkg, foreign), foreign)
    package_backed = {"index", "forecast", "should_cost", "order_history"} & known
    assert package_backed, known
    assert package_backed <= got, (known, got)


def test_unknown_refs_are_cited_without_a_figure(pkg):
    case = next(iter(load_cases().values()))
    foreign = {**case, "refs": ["cost:part:NEW", "po:4500009999", "po:4500009998"]}
    claims = ClaimBank(pkg, foreign).for_supplier(supplier(case), HIGH)
    by_ids = {tuple(c["ids"]): c for c in claims}
    assert ("cost:part:NEW",) in by_ids
    assert ("po:4500009999", "po:4500009998") in by_ids
    assert "EUR" not in by_ids[("cost:part:NEW",)]["text"]
