"""Replay the dualtor pretest scenarios through DynamicParallelBisect with the
new verification round, comparing:

  Scenario A: buildimage-style, where the regression is REAL.
              Verification round must confirm predecessor=good, candidate=bad
              and the algorithm must report outcome=bad_commit.

  Scenario B: sonic-mgmt build 1129277, where the test is FLAKY.  The 3-round
              search converges to a640a0b but the predecessor 75436ba was
              tested 'good' in round 2 (different infra state).  Re-run in
              the same verification round, the flakiness is exposed and the
              algorithm must report outcome=flaky_verification (NOT bad_commit).

Run from `pr_workspace/test_analyzer/`:
    python -m pr_binary_search.tests.replay_dualtor_scenarios
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

# Make sibling import work whether we run from pr_workspace/test_analyzer/
# or anywhere else.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from pr_binary_search.binary_plan import DynamicParallelBisect  # noqa: E402


# Oldest -> newest, mirroring how pr_binary_search feeds the commit list.
DUALTOR_COMMITS: List[str] = [
    "75436ba",   # 0  parent of the candidate, tested 'good' in round 2 of build 1129277
    "a640a0b",   # 1  candidate flagged by build 1129277 round 3
    "c1d8586",   # 2
    "5fdd4c68",  # 3  tested 'bad' in build 1129277 round 2
    "b9db7bbf",  # 4  tested 'bad' in build 1129277 round 1
    "b987887",   # 5  newest
]


def stable_oracle(true_first_bad_idx: int):
    """Stable oracle: idx < true_first_bad_idx is good, else bad. Independent of round."""
    def oracle(commits: List[str], plan: Dict) -> Dict[str, bool]:
        out = {}
        for sha in plan["tests"]:
            idx = commits.index(sha)
            out[sha] = idx >= true_first_bad_idx
        return out
    return oracle


def flaky_oracle(true_first_bad_idx: int, flips: Dict[str, List[int]]):
    """Oracle that mostly behaves like `stable_oracle` but flips specific
    SHAs in specific rounds.  `flips[sha] = [round_no, ...]` means: in those
    rounds the verdict for `sha` is the opposite of the stable verdict.
    """
    def oracle(commits: List[str], plan: Dict) -> Dict[str, bool]:
        out = {}
        rno = plan["round"]
        for sha in plan["tests"]:
            idx = commits.index(sha)
            stable = idx >= true_first_bad_idx
            if sha in flips and rno in flips[sha]:
                out[sha] = not stable
            else:
                out[sha] = stable
        return out
    return oracle


def run_scenario(name: str, commits: List[str], oracle, verify_convergence: bool = True,
                 max_rounds: int = 8) -> Dict:
    print("=" * 78)
    print(f"SCENARIO: {name}")
    print("=" * 78)
    bisect = DynamicParallelBisect(commits, max_parallel=5,
                                   verify_convergence=verify_convergence)
    while not bisect.finished and bisect.round_no < max_rounds:
        plan = bisect.next_plan()
        if plan is None:
            break
        verdicts = oracle(commits, plan)
        tag = " [VERIFICATION]" if plan.get("verification") else ""
        print(f"  round {plan['round']}{tag}  range={plan['range']}  "
              f"tests={plan['tests']}")
        for sha in plan["tests"]:
            v = verdicts.get(sha, "<missing>")
            print(f"      {sha:10s} -> {'BAD' if v is True else ('GOOD' if v is False else v)}")
        bisect.update(verdicts)

    # Summarize.
    if bisect.result is not None:
        outcome = "bad_commit"
    elif bisect.inconclusive_reason:
        outcome = bisect.inconclusive_reason
    else:
        outcome = "no_bad_commit_found"

    print(f"  -> result_sha          = {bisect.result}")
    print(f"  -> inconclusive_reason = {bisect.inconclusive_reason}")
    print(f"  -> outcome (RootCauseType) = {outcome}")
    print(f"  -> verification_round_no    = {bisect.verification_round_no}")
    print(f"  -> verification_results     = {bisect.verification_results}")
    print()
    return {
        "outcome": outcome,
        "result": bisect.result,
        "verification_round_no": bisect.verification_round_no,
        "verification_results": bisect.verification_results,
    }


# --------------------------------------------------------------------------- #
# Scenario A: buildimage-style — regression is REAL.
# Stable oracle: idx 0 is good, idx >= 1 is bad.  Verification round will
# confirm predecessor=good, candidate=bad.
# --------------------------------------------------------------------------- #
oracle_real = stable_oracle(true_first_bad_idx=1)

# --------------------------------------------------------------------------- #
# Scenario B1: sonic-mgmt 1129277 — TEST IS FLAKY: predecessor 75436ba was
# truly bad all along (the regression actually predates the search window),
# but happened to test 'good' once in round 2.  In the verification round
# (round 4) it shows its true colors.
# --------------------------------------------------------------------------- #
oracle_flaky_predecessor = flaky_oracle(
    true_first_bad_idx=0,                           # ALL commits are bad in truth
    flips={"75436ba": [2]},                         # but 75436ba flaked good in round 2
)

# --------------------------------------------------------------------------- #
# Scenario B2: same flaky test but the candidate is what flips.  In round 3
# a640a0b reads bad, but in the verification round (round 4) it reads good
# — exposing the flakiness at the candidate end of the range.
# --------------------------------------------------------------------------- #
oracle_flaky_candidate = flaky_oracle(
    true_first_bad_idx=1,                           # nominally idx>=1 bad
    flips={"a640a0b": [4]},                         # but a640a0b flips good in verification
)

# --------------------------------------------------------------------------- #
# Scenario D: regression actually lives in sonic-buildimage
# (e.g. 997516e5f...).  Every sonic-mgmt commit in the search window will
# therefore test BAD against the buggy image.  The correct verdict is "no
# in-window bad commit" — algorithm must take the existing
# `regression_predates_window` short-circuit and MUST NOT enter the
# verification round (left==0 at convergence).
# --------------------------------------------------------------------------- #
oracle_predates_window = stable_oracle(true_first_bad_idx=0)   # all commits bad


# --------------------------------------------------------------------------- #
# BUILDIMAGE-side scenarios.  The actual bad commit reported by the user is
# `997516e5f84c9f44253a1120e6bce7a495cfff78` in sonic-buildimage.  We mirror
# a representative search window of 8 buildimage commits (oldest -> newest)
# with 997516e5 sitting at index 5 — i.e. neither the leftmost nor the
# rightmost commit, so the search has to find it via narrowing and the
# verification round will be exercised in the normal way.
# --------------------------------------------------------------------------- #
BUILDIMAGE_BAD = "997516e5f84c9f44253a1120e6bce7a495cfff78"
BUILDIMAGE_COMMITS: List[str] = [
    "11111111111111111111111111111111111111aa",  # 0  good baseline
    "22222222222222222222222222222222222222bb",  # 1  good
    "33333333333333333333333333333333333333cc",  # 2  good
    "44444444444444444444444444444444444444dd",  # 3  good
    "55555555555555555555555555555555555555ee",  # 4  predecessor of the bad commit
    BUILDIMAGE_BAD,                              # 5  THE bad commit (truth)
    "77777777777777777777777777777777777777ff",  # 6  inherits the regression -> bad
    "88888888888888888888888888888888888888aa",  # 7  newest, also bad
]
BUILDIMAGE_BAD_IDX = BUILDIMAGE_COMMITS.index(BUILDIMAGE_BAD)
BUILDIMAGE_PREDECESSOR = BUILDIMAGE_COMMITS[BUILDIMAGE_BAD_IDX - 1]

# E. Stable, real regression — algorithm must converge on 997516e5 and
# verification must confirm it.
oracle_buildimage_stable = stable_oracle(true_first_bad_idx=BUILDIMAGE_BAD_IDX)

# F. Real regression but the verification round catches a transient flake on
# the predecessor (it tests bad once during verification despite truly being
# good).  The PR is conservative on purpose: rather than risk reverting the
# wrong commit, we abstain via flaky_verification and the operator can
# re-trigger the search.
oracle_buildimage_flake_pred = flaky_oracle(
    true_first_bad_idx=BUILDIMAGE_BAD_IDX,
    flips={BUILDIMAGE_PREDECESSOR: [4]},        # round 4 is the verification round
)


def main() -> int:
    results = []
    results.append(("A. buildimage real regression (verify ON)",
                    run_scenario("A. buildimage real regression (verify ON)",
                                 DUALTOR_COMMITS, oracle_real)))

    results.append(("B1. sonic-mgmt 1129277, flaky predecessor (verify ON)",
                    run_scenario("B1. sonic-mgmt 1129277, flaky predecessor (verify ON)",
                                 DUALTOR_COMMITS, oracle_flaky_predecessor)))

    results.append(("B2. sonic-mgmt 1129277, flaky candidate  (verify ON)",
                    run_scenario("B2. sonic-mgmt 1129277, flaky candidate  (verify ON)",
                                 DUALTOR_COMMITS, oracle_flaky_candidate)))

    results.append(("C. same flaky input, verification DISABLED (old behavior)",
                    run_scenario("C. same flaky input, verification DISABLED (old behavior)",
                                 DUALTOR_COMMITS, oracle_flaky_predecessor,
                                 verify_convergence=False)))

    results.append(("D. regression lives in buildimage (all mgmt commits bad)",
                    run_scenario("D. regression lives in buildimage (all mgmt commits bad)",
                                 DUALTOR_COMMITS, oracle_predates_window)))

    results.append(("E. buildimage search finds 997516e5 (stable, verify ON)",
                    run_scenario("E. buildimage search finds 997516e5 (stable, verify ON)",
                                 BUILDIMAGE_COMMITS, oracle_buildimage_stable)))

    results.append(("F. buildimage search, predecessor flakes in verification",
                    run_scenario("F. buildimage search, predecessor flakes in verification",
                                 BUILDIMAGE_COMMITS, oracle_buildimage_flake_pred)))

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for name, r in results:
        print(f"  {name}")
        print(f"      -> outcome={r['outcome']:24s}  result={r['result']}")

    # Assertions encoding what the user asked us to demonstrate.
    assert results[0][1]["outcome"] == "bad_commit",         "A: real regression must be confirmed"
    assert results[0][1]["result"] == "a640a0b",             "A: must blame a640a0b"
    assert results[1][1]["outcome"] == "flaky_verification", "B1: predecessor flake must NOT pin a commit"
    assert results[1][1]["result"] is None,                  "B1: result must be None"
    assert results[2][1]["outcome"] == "flaky_verification", "B2: candidate flake must NOT pin a commit"
    assert results[2][1]["result"] is None,                  "B2: result must be None"
    assert results[3][1]["outcome"] == "bad_commit",         "C: old behavior would falsely blame a640a0b"
    assert results[3][1]["result"] == "a640a0b",             "C: documents the regression we are fixing"
    # D: the regression is actually in sonic-buildimage (997516e5f...).  Every
    # mgmt commit in the search window tests bad.  The CORRECT outcome is no
    # bad commit blamed and root cause = regression_predates_window.  The
    # verification round MUST NOT run (it only fires when left>0 at convergence).
    assert results[4][1]["outcome"] == "regression_predates_window", \
        "D: every-commit-bad must short-circuit to predates_window, not flaky_verification"
    assert results[4][1]["result"] is None,                  "D: must not blame any mgmt commit"
    assert results[4][1]["verification_round_no"] is None,   "D: verification round must NOT trigger"

    # E: stable buildimage regression -- algorithm must converge on 997516e5
    # AND the verification round must confirm it (predecessor good, candidate bad).
    assert results[5][1]["outcome"] == "bad_commit",         "E: must declare a bad commit"
    assert results[5][1]["result"] == BUILDIMAGE_BAD,        "E: must blame 997516e5"
    assert results[5][1]["verification_round_no"] is not None, "E: verification must run"
    vr_e = results[5][1]["verification_results"]
    assert vr_e[BUILDIMAGE_PREDECESSOR] is False,            "E: verified predecessor good"
    assert vr_e[BUILDIMAGE_BAD] is True,                     "E: verified candidate bad"

    # F: real regression at 997516e5 but predecessor flakes during the
    # verification round.  PR refuses to blame on flaky evidence.
    assert results[6][1]["outcome"] == "flaky_verification", "F: predecessor flake must abstain"
    assert results[6][1]["result"] is None,                  "F: must not blame anyone"

    print()
    print("ALL ASSERTIONS PASSED  PR successfully discriminates real vs flaky.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
