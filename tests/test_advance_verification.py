"""Tests that advance is blocked when verification fails."""
import sagtask


class TestAdvanceVerification:
    def _create_task_with_verification(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-adv-verify",
            "name": "Test Advance Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [
                    {
                        "id": "step-1",
                        "name": "Step 1",
                        "verification": {"commands": ["true"], "must_pass": True},
                    },
                    {"id": "step-2", "name": "Step 2"},
                ],
            }],
        })

    def test_advance_blocked_when_verification_fails(self, isolated_sagtask, mock_git):
        """Advance should be blocked if verification must_pass and last_verification failed."""
        self._create_task_with_verification(isolated_sagtask, mock_git)
        state = isolated_sagtask.load_task_state("test-adv-verify")
        state["methodology_state"]["last_verification"] = {
            "passed": False,
            "timestamp": "2026-05-07T00:00:00Z",
            "results": [{"command": "pytest", "exit_code": 1, "stdout": "", "stderr": "1 failed"}],
        }
        isolated_sagtask.save_task_state("test-adv-verify", state)
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-adv-verify"})
        assert result["ok"] is False
        assert "verification" in result["error"].lower() or "verify" in result["error"].lower()

    def test_advance_allowed_when_verification_passes(self, isolated_sagtask, mock_git):
        """Advance should proceed if verification passed."""
        self._create_task_with_verification(isolated_sagtask, mock_git)
        state = isolated_sagtask.load_task_state("test-adv-verify")
        state["methodology_state"]["last_verification"] = {
            "passed": True,
            "timestamp": "2026-05-07T00:00:00Z",
            "results": [{"command": "true", "exit_code": 0, "stdout": "", "stderr": ""}],
        }
        isolated_sagtask.save_task_state("test-adv-verify", state)
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-adv-verify"})
        assert result["ok"] is True

    def test_advance_allowed_without_verification(self, isolated_sagtask, mock_git):
        """Advance should proceed if no verification is configured."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-adv-no-verify",
            "name": "No Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [
                    {"id": "step-1", "name": "Step 1"},
                    {"id": "step-2", "name": "Step 2"},
                ],
            }],
        })
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-adv-no-verify"})
        assert result["ok"] is True

    def test_advance_allowed_when_must_pass_false(self, isolated_sagtask, mock_git):
        """Advance should proceed if verification.must_pass is False."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-adv-not-mandatory",
            "name": "Not Mandatory",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [
                    {
                        "id": "step-1",
                        "name": "Step 1",
                        "verification": {"commands": ["false"], "must_pass": False},
                    },
                    {"id": "step-2", "name": "Step 2"},
                ],
            }],
        })
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-adv-not-mandatory"})
        assert result["ok"] is True
