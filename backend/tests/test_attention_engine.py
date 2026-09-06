"""The triage list.

What matters here is not that it returns rows. It is that it stays quiet when
nothing is wrong, that it never shows the same incident twice, and that the
ordering puts the thing nobody is working on above the thing somebody already
is - because those three properties are the entire difference between a triage
list and the wall of numbers it replaced.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from reversa.engines.attention_engine import (  # noqa: E402
    MATERIAL_PAISE, Item, Urgency, _collapse, _name, summarise,
)


class _Inc:
    """Enough of an Incident to name it."""

    def __init__(self, method=None, instrument=None):
        self.slice_method = method
        self.slice_instrument = instrument


def item(kind, urgency, money, *, incident=None, headline="h"):
    return Item(
        kind=kind, urgency=urgency, headline=headline, detail="d",
        money_paise=money, action_label="go", action_path="/x",
        evidence={"incident_id": incident} if incident else {},
    )


# --- naming -----------------------------------------------------------------

def test_a_slice_is_named_the_way_somebody_would_say_it():
    assert _name(_Inc("upi")) == "UPI"
    assert _name(_Inc("card", "VISA")) == "CARD / VISA"


def test_the_unattributed_slice_reads_as_a_phrase_not_a_key():
    """`*/*` is right for a database and wrong for a sentence.

    Lower case on purpose: every headline places it mid-sentence, and
    "Nothing is running against Several unrelated slices" reads like a bug.
    """
    assert _name(_Inc()) == "several unrelated slices"


# --- collapsing -------------------------------------------------------------

def test_one_incident_never_takes_more_than_one_row():
    """The regression this file exists for.

    Three rules can fire on one broken slice - nothing running, cause unknown,
    feed silent. The first version listed all three, which is how a triage list
    turns back into the clutter it was meant to replace.
    """
    rows = _collapse([
        item("unattended", Urgency.ACT, 100, incident="inc_1"),
        item("unresolved_cause", Urgency.REVIEW, 100, incident="inc_1"),
        item("blind_window", Urgency.WATCH, 100, incident="inc_1"),
    ])
    assert len(rows) == 1


def test_the_most_urgent_framing_wins_the_row():
    rows = _collapse([
        item("blind_window", Urgency.WATCH, 100, incident="inc_1"),
        item("unattended", Urgency.ACT, 100, incident="inc_1"),
    ])
    assert rows[0].urgency == Urgency.ACT
    assert rows[0].kind == "unattended"


def test_the_losing_reasons_survive_as_notes_rather_than_vanishing():
    """Collapsing must not be the same as discarding.

    The second and third facts are worth knowing; they are just not worth a
    second and third line.
    """
    rows = _collapse([
        item("unattended", Urgency.ACT, 100, incident="inc_1", headline="nothing running"),
        item("blind_window", Urgency.WATCH, 100, incident="inc_1", headline="feed silent"),
    ])
    assert rows[0].evidence["also"] == ["feed silent"]


def test_collapsing_keeps_the_larger_amount_at_stake():
    rows = _collapse([
        item("unattended", Urgency.ACT, 100, incident="inc_1"),
        item("unresolved_cause", Urgency.REVIEW, 900, incident="inc_1"),
    ])
    assert rows[0].money_paise == 900


def test_items_with_no_incident_are_never_merged_together():
    """Capacity pressure and a stalled review queue are unrelated problems.

    They share the trait of having no incident id, which must not be read as
    them being the same thing.
    """
    rows = _collapse([
        item("capacity_pressure", Urgency.WATCH, 0),
        item("awaiting_review", Urgency.REVIEW, 500),
    ])
    assert len(rows) == 2


def test_separate_incidents_stay_separate():
    rows = _collapse([
        item("unattended", Urgency.ACT, 100, incident="inc_1"),
        item("unattended", Urgency.ACT, 100, incident="inc_2"),
    ])
    assert len(rows) == 2


# --- the summary ------------------------------------------------------------

def test_an_empty_list_says_so_rather_than_rendering_nothing():
    """A blank panel looks like a failed request. Silence has to be explicit."""
    s = summarise([])
    assert s["all_clear"] is True
    assert s["total"] == 0
    assert s["money_at_stake_paise"] == 0


def test_money_at_stake_counts_only_what_nobody_is_working_on():
    """The headline number is what is bleeding, not what is queued.

    Adding a review-queue value into the same figure would double count money
    that is already being handled, and inflate the one number an operator is
    most likely to repeat out loud.
    """
    s = summarise([
        item("unattended", Urgency.ACT, 700, incident="a"),
        item("awaiting_review", Urgency.REVIEW, 500),
    ])
    assert s["money_at_stake_paise"] == 700
    assert s["act"] == 1


def test_the_materiality_floor_is_high_enough_to_mean_something():
    """A threshold of a few hundred rupees would let noise through.

    Observed exposure on real incidents runs into lakhs, so the floor exists to
    keep small true positives off a list that is meant to be interrupting.
    """
    assert MATERIAL_PAISE >= 10_000_00


def test_the_payload_carries_what_the_dashboard_needs_to_render_a_row():
    s = summarise([item("unattended", Urgency.ACT, 700, incident="a")])
    row = s["items"][0]
    assert set(row) >= {
        "kind", "urgency", "headline", "detail",
        "money_paise", "action_label", "action_path",
    }
    assert row["action_path"].startswith("/")
