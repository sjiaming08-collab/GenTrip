from src.models.session import SessionState, Turn


def test_session_state_keeps_recent_five_turns():
    session = SessionState(session_id="s1")
    for idx in range(7):
        session.add_turn(Turn(turn_id=str(idx), user_query=f"q{idx}", reply_type="route"))

    assert session.turn_count == 7
    assert [turn.turn_id for turn in session.recent_turns] == ["2", "3", "4", "5", "6"]
