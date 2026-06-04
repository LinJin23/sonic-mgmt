from typing import List, Dict, Optional, Tuple


def choose_optimal_segments(n: int, max_parallel: int) -> int:
    """
    Choose optimal number of segments for current range size n and max parallel limit.
    Returns the number of segments to divide the range into.
    """
    if n <= 2:
        return n

    # For binary search efficiency, we want to divide the range optimally
    # But limit by max_parallel to avoid too many concurrent tests

    # Optimal would be to test roughly half the range, but spread out
    # For range n, testing k points gives us k+1 segments
    # We want k <= max_parallel
    max_segments = max_parallel + 1
    optimal_segments = min((max_segments), max(3, int(n ** 0.5)))

    # Ensure we don't create more segments than we have commits
    return min(optimal_segments, n)


def compute_indices(left: int, right: int, f: int) -> List[int]:
    """
    Divide [left,right] into f segments (f>=1), return boundary point indices (length = f-1).
    Each segment length differs by at most 1.
    """
    n = right - left + 1
    if f <= 1 or n <= 1:
        return []
    q, r = divmod(n, f)
    sizes = [q+1]*r + [q]*(f-r)
    indices = []
    prefix = 0
    for j in range(len(sizes)-1):
        prefix += sizes[j]
        idx = left + prefix - 1
        if not indices or idx > indices[-1]:
            indices.append(idx)
    return indices


class DynamicParallelBisect:
    # Sentinel reasons for an inconclusive search.  Strings are used as-is in
    # the Kusto `RootCauseType` column, so do not change them lightly.
    INCONCLUSIVE_PREDATES_WINDOW = "regression_predates_window"
    # Final verification round disagreed with the binary-search verdict (e.g.
    # the predecessor re-tested as bad, or the candidate re-tested as good).
    # We refuse to blame a single commit on flaky/unstable evidence.
    INCONCLUSIVE_FLAKY_VERIFICATION = "flaky_verification"

    # Internal verification state machine.
    _VERIFY_NOT_STARTED = "not_started"
    _VERIFY_QUEUED = "queued"
    _VERIFY_DONE = "done"

    def __init__(self, commits: List[str], max_parallel: int = 5, bad_commit_checker=None,
                 verify_convergence: bool = True):
        if verify_convergence and max_parallel < 2:
            # The final verification round always tests two commits in parallel
            # (candidate + immediate predecessor).  We must ensure the configured
            # concurrency budget can accommodate that pair, otherwise
            # `next_plan()` would emit a round that violates the caller's
            # `max_parallel` contract.  Callers that genuinely need
            # `max_parallel < 2` must opt out of verification explicitly.
            raise ValueError(
                "verify_convergence=True requires max_parallel >= 2 "
                "(verification round tests candidate + predecessor in parallel); "
                "got max_parallel={}".format(max_parallel)
            )
        self.commits = commits
        self.N = len(commits)
        self.max_parallel = max_parallel
        self.left = 0
        self.right = self.N - 1
        self.round_no = 0
        self.finished = False
        self.result = None
        # When the search converges on the leftmost commit of the window
        # without ever having advanced `left` past index 0, it means we
        # never observed a known-good lower-bound anchor.  We cannot blame
        # the leftmost commit in that case: the regression most likely
        # predates the search window (e.g. it was introduced in
        # sonic-buildimage or in an older sonic-mgmt commit).  These
        # attributes are populated by `update()` and consumed by the
        # orchestrator / Kusto record builder.
        self.inconclusive_reason: Optional[str] = None
        self.oldest_bad_commit: Optional[str] = None
        self.bad_commit_checker = bad_commit_checker

        # Final-verification step.  When the binary search would otherwise
        # finalize on a commit `cid` at `self.left == self.right`, we first
        # schedule a single extra round that *re-tests `cid` and its
        # immediate predecessor `commits[self.left - 1]` together in
        # parallel*.  Only when the verification round says
        # `predecessor=good AND candidate=bad` do we accept the verdict;
        # otherwise we mark the search inconclusive (flaky_verification).
        # This guards against:
        #   - flaky test results during the binary search (the predecessor
        #     was tested "good" several rounds earlier in a different infra
        #     state — flakiness may have flipped since),
        #   - off-by-one narrowing bugs,
        #   - incomplete commit lists where the list-predecessor isn't the
        #     real git parent of the candidate.
        # When `verify_convergence` is False (e.g. for unit tests of legacy
        # behaviour) the verification step is skipped.
        self.verify_convergence = verify_convergence
        self._verify_state = self._VERIFY_NOT_STARTED
        self._verify_candidate_idx: Optional[int] = None
        self._verify_predecessor_idx: Optional[int] = None
        # Public diagnostics for the orchestrator / Kusto record.
        self.verification_round_no: Optional[int] = None
        self.verification_results: Optional[Dict[str, bool]] = None

    def update(self, results: Dict[str, bool]):
        """
        results: {commit_id: True/False}, True = bad
        Update left/right based on parallel test results from this round.
        """
        if self.finished:
            return

        # If we previously queued a final verification round, this `results`
        # dict carries the verification answers.  Handle them separately and
        # do NOT feed them through the normal narrowing logic (which would
        # otherwise re-narrow `left`/`right` based on a single re-test).
        if self._verify_state == self._VERIFY_QUEUED:
            self._handle_verification_results(results)
            return

        # Find the leftmost bad commit in this round
        bad_idx = None
        for idx in range(self.left, self.right + 1):
            cid = self.commits[idx]
            if cid in results and results[cid]:
                bad_idx = idx
                break

        if bad_idx is None:
            # No bad commit in this round, all tested commits are good
            # Find the rightmost tested commit, then set left to the next position
            tested_indices = []
            for idx in range(self.left, self.right + 1):
                cid = self.commits[idx]
                if cid in results:
                    tested_indices.append(idx)

            if tested_indices:
                # Set left to the next position after the rightmost tested commit
                self.left = max(tested_indices) + 1
            else:
                # If no commit was tested, this shouldn't happen
                self.left = self.right + 1
        else:
            # Found bad commit, need to consider both bad and good commits
            # The search range should be: (rightmost_good + 1) to bad_commit

            # Find the rightmost good commit among tested commits
            rightmost_good_idx = None
            for idx in range(self.left, bad_idx):  # Only check commits before the bad one
                cid = self.commits[idx]
                if cid in results and not results[cid]:  # Good commit
                    if rightmost_good_idx is None or idx > rightmost_good_idx:
                        rightmost_good_idx = idx

            # Update the search range
            if rightmost_good_idx is not None:
                # Set left to the position after the rightmost good commit
                self.left = rightmost_good_idx + 1
            # Set right to the bad commit's position
            self.right = bad_idx

        # Check if finished.
        # When left > right the whole range is exhausted with no bad commit.
        # When left == right we only mark finished if the sole remaining commit
        # was confirmed BAD in this very round; otherwise it still needs testing
        # (e.g. the range was just narrowed down to it by eliminating good commits).
        if self.left > self.right:
            self.finished = True
            self.result = None  # No bad commit found
        elif self.left == self.right:
            cid = self.commits[self.left]
            if cid in results and results.get(cid) is True:
                # The single remaining commit was tested this round and is bad.
                # `self.left` is only ever advanced by observing a good commit
                # that bounds the search from below (see the two branches above).
                # So `self.left == 0` at convergence is exactly equivalent to
                # "no known-good lower-bound anchor was ever observed".  In that
                # case we cannot legitimately blame the leftmost commit — the
                # regression most likely predates the search window (e.g. it
                # was introduced in sonic-buildimage or in an older sonic-mgmt
                # commit).  Report this as inconclusive while keeping the
                # oldest tested bad commit for operator diagnostics.
                if self.left == 0:
                    self.finished = True
                    self.result = None
                    self.inconclusive_reason = self.INCONCLUSIVE_PREDATES_WINDOW
                    self.oldest_bad_commit = cid
                elif (
                    self.verify_convergence
                    and self._verify_state == self._VERIFY_NOT_STARTED
                ):
                    # Defer finalization: schedule a verification round that
                    # re-tests the candidate AND its immediate predecessor
                    # together in parallel.  Only when the predecessor comes
                    # back good and the candidate comes back bad do we accept
                    # the verdict.  See class docstring for rationale.
                    self._verify_state = self._VERIFY_QUEUED
                    self._verify_candidate_idx = self.left
                    self._verify_predecessor_idx = self.left - 1
                    # Leave `self.finished` False so `next_plan()` schedules
                    # the verification round.
                else:
                    # Verification disabled, or this branch was reached after
                    # verification already ran (defensive).
                    self.finished = True
                    self.result = cid
            # else: leave finished=False so next_plan() schedules it for testing.

    def _handle_verification_results(self, results: Dict[str, bool]):
        """Finalize the search based on a verification round's test results.

        The verification round always tests exactly two commits in parallel:
        the candidate at `self._verify_candidate_idx` and its predecessor at
        `self._verify_predecessor_idx`.  We accept the binary-search verdict
        if and only if predecessor=good AND candidate=bad.  Any other outcome
        is reported as `flaky_verification` so downstream consumers do not
        falsely revert a commit on flaky evidence.
        """
        candidate_sha = self.commits[self._verify_candidate_idx]
        predecessor_sha = self.commits[self._verify_predecessor_idx]
        candidate_bad = results.get(candidate_sha)
        predecessor_bad = results.get(predecessor_sha)

        self.verification_round_no = self.round_no
        self.verification_results = {
            predecessor_sha: predecessor_bad,
            candidate_sha: candidate_bad,
        }
        self._verify_state = self._VERIFY_DONE
        self.finished = True

        if candidate_bad is True and predecessor_bad is False:
            # Verdict confirmed: predecessor is good, candidate is bad.
            self.result = candidate_sha
            self.inconclusive_reason = None
        else:
            # Any other outcome (predecessor also bad, candidate now good,
            # missing results) is treated as flaky / unverifiable.  Refuse to
            # blame a commit on this evidence.
            self.result = None
            self.inconclusive_reason = self.INCONCLUSIVE_FLAKY_VERIFICATION
            # Surface the candidate SHA for diagnostics so operators can see
            # which commit was tentatively flagged but failed verification.
            self.oldest_bad_commit = candidate_sha

    def next_plan(self) -> Optional[Dict]:
        """Return the next round plan"""
        if self.finished:
            return None

        self.round_no += 1

        # If a final verification round was queued by `update()`, schedule it
        # now.  We test the candidate AND its predecessor together in
        # parallel so the verdict is grounded in a single, consistent test
        # environment (guards against cross-round flakiness drift).
        if self._verify_state == self._VERIFY_QUEUED:
            cand_idx = self._verify_candidate_idx
            pred_idx = self._verify_predecessor_idx
            tests = [self.commits[pred_idx], self.commits[cand_idx]]
            return {"round": self.round_no,
                    "tests": tests,
                    "indices": [pred_idx, cand_idx],
                    "range": (self.left, self.right),
                    "final": True,
                    "verification": True}

        # Check if already converged to a single commit â€” return it for testing but
        # do NOT pre-declare finished/result here; let update() decide based on the
        # actual test outcome (so an all-good range correctly yields result=None).
        if self.left == self.right:
            return {"round": self.round_no,
                    "tests": [self.commits[self.left]],
                    "indices": [self.left],
                    "range": (self.left, self.right),
                    "final": True}

        # Check if out of range
        if self.left > self.right or self.left >= len(self.commits):
            self.finished = True
            return None

        n = self.right - self.left + 1

        # For small ranges, just test the middle
        if n <= 2:
            mid = (self.left + self.right) // 2
            return {"round": self.round_no,
                    "tests": [self.commits[mid]],
                    "indices": [mid],
                    "range": (self.left, self.right),
                    "final": False}

        # Choose optimal number of segments based on range size and max_parallel
        f_here = choose_optimal_segments(n, self.max_parallel)
        indices = compute_indices(self.left, self.right, f_here)

        # Ensure indices are within valid range and limit by max_parallel
        indices = [i for i in indices if self.left <= i <= self.right]
        if len(indices) > self.max_parallel:
            # If we have too many indices, select evenly spaced ones
            step = max(1, len(indices) // self.max_parallel)
            indices = indices[::step][:self.max_parallel]

        tests = [self.commits[i] for i in indices]

        return {"round": self.round_no,
                "tests": tests,
                "indices": indices,
                "segments": f_here,
                "range": (self.left, self.right),
                "final": False}

    def get_result(self) -> Tuple[Optional[str], Tuple[int, int]]:
        if self.result is not None:
            return self.result, (self.left, self.right)
        else:
            return None, (self.left, self.right)

    def find_bad_commit_auto(self, bad_commit_checker) -> Optional[str]:
        """
        Automatically find the first bad commit using the provided checker function.
        bad_commit_checker: function that takes a commit_id and returns True if bad, False if good
        """
        self.bad_commit_checker = bad_commit_checker

        while True:
            plan = self.next_plan()
            if plan is None:
                break

            # Test all commits in the plan
            results = {}
            for commit_id in plan['tests']:
                results[commit_id] = self.bad_commit_checker(commit_id)

            self.update(results)

            if self.finished:
                break

        result, _ = self.get_result()
        return result

    def get_next_test_commits(self) -> Optional[Dict]:
        """
        Get the next batch of commits to test (without automatically testing them).
        Returns a plan dict with commits to test, or None if finished.

        Returns:
            Dict with keys:
            - 'round': current round number
            - 'tests': list of commit IDs to test
            - 'indices': list of indices of commits to test
            - 'range': current search range (left, right)
            - 'remaining_range': number of commits in current range
            - 'final': whether this is the final test
        """
        plan = self.next_plan()
        if plan is None:
            return None

        # Add additional info for user convenience
        plan['remaining_range'] = self.right - self.left + 1
        plan['current_range_commits'] = self.commits[self.left:self.right + 1]

        return plan

    def submit_test_results(self, results: Dict[str, bool]) -> Dict:
        """
        Submit the test results and get updated status.

        Args:
            results: Dict mapping commit_id to test result (True=bad, False=good)

        Returns:
            Dict with status information:
            - 'finished': whether search is complete
            - 'result': the bad commit if found, None otherwise
            - 'new_range': updated search range (left, right)
            - 'new_range_commits': commits in the new range
            - 'eliminated_commits': commits that were eliminated this round
        """
        assert all(v is not None for v in results.values()), (
            "submit_test_results received None result values; filter incomplete results before calling"
        )
        old_left, old_right = self.left, self.right
        old_range_commits = self.commits[old_left:old_right + 1]

        self.update(results)

        new_range_commits = []
        if not self.finished and self.left <= self.right:
            new_range_commits = self.commits[self.left:self.right + 1]

        # Calculate eliminated commits
        eliminated_commits = [c for c in old_range_commits if c not in new_range_commits]

        result, _ = self.get_result()

        return {
            'finished': self.finished,
            'result': result,
            'new_range': (self.left, self.right) if not self.finished else None,
            'start': self.left,
            'end': self.right,
            'eliminated_commits': eliminated_commits,
            'round_completed': self.round_no,
            'inconclusive_reason': self.inconclusive_reason,
            'oldest_bad_commit': self.oldest_bad_commit,
            'verification_pending': self._verify_state == self._VERIFY_QUEUED,
            'verification_round_no': self.verification_round_no,
            'verification_results': self.verification_results,
        }

    def get_search_status(self) -> Dict:
        """Get current search status"""
        result, _ = self.get_result()
        return {
            'finished': self.finished,
            'result': result,
            'current_round': self.round_no,
            'current_range': (self.left, self.right),
            'current_range_commits': self.commits[self.left:self.right + 1] if self.left <= self.right else [],
            'remaining_commits': self.right - self.left + 1 if self.left <= self.right else 0,
            'max_parallel': self.max_parallel,
            'inconclusive_reason': self.inconclusive_reason,
            'oldest_bad_commit': self.oldest_bad_commit,
            'verification_pending': self._verify_state == self._VERIFY_QUEUED,
            'verification_round_no': self.verification_round_no,
            'verification_results': self.verification_results,
        }
