# ABOUTME: End-to-end smoke test for the v0.4 block-and-recover flow.
# ABOUTME: Verifies hook block writes a usable pending entry and the squeezed text resolves correctly.

import hashlib


def test_long_prompt_blocks_and_pending_resolves_to_squeezed_text(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    import pending_cache
    from user_prompt_submit import _process

    sid = "integration_test_session"
    sh = hashlib.sha256(sid.encode()).hexdigest()[:16]

    long_prompt = "Please could you help me " + "explain async/await in Python " * 200
    payload = {
        "session_id": sid,
        "cwd": str(tmp_path),
        "prompt": long_prompt,
    }

    result = _process(payload)
    out = result["output"]

    # Hook blocked
    assert out.get("decision") == "block"
    reason = out["reason"]
    assert "/sq y" in reason

    # Pending cache has an entry
    entry = pending_cache.read_pending(sh)
    assert entry is not None
    assert entry["consumed"] is False
    assert "squeezed_text" in entry

    # The squeezed text is what /sq y would emit
    squeezed = entry["squeezed_text"]
    assert len(squeezed) > 0
    assert len(squeezed) < len(long_prompt)
    # And it preserves the topic
    assert "async/await" in squeezed
    # Original NOT stored when explain is off (the default)
    assert "original_text" not in entry


def test_yes_session_consent_produces_terse_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    import session_state
    from user_prompt_submit import _process

    sid = "integration_terse_banner_session"
    sh = hashlib.sha256(sid.encode()).hexdigest()[:16]

    # Pre-grant consent for the session
    session_state.write_consent(sh, "yes-session")

    long_prompt = "Please could you " + "explain async/await in Python " * 200
    payload = {
        "session_id": sid,
        "cwd": str(tmp_path),
        "prompt": long_prompt,
    }

    result = _process(payload)
    out = result["output"]

    assert out.get("decision") == "block"
    reason = out["reason"]
    # Terse banner does NOT include the full three-choice menu
    assert "/sq y" in reason
    assert "y session" not in reason
    # And it should mention "auto:" prefix to signal the auto-confirm flow
    assert "auto:" in reason


def test_no_consent_passes_through(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    import session_state
    from user_prompt_submit import _process

    sid = "integration_consent_no_session"
    sh = hashlib.sha256(sid.encode()).hexdigest()[:16]

    session_state.write_consent(sh, "no")

    long_prompt = "Please could you " + "explain async/await in Python " * 200
    payload = {
        "session_id": sid,
        "cwd": str(tmp_path),
        "prompt": long_prompt,
    }

    result = _process(payload)
    out = result["output"]

    # User opted out — no block
    assert "decision" not in out
    # Log row records the consent state
    assert result["log"]["consent"] == "no"
    assert result["log"]["action"] == "consent_no"
