from __future__ import annotations

from pathlib import Path

import pytest
from anki.collection import Collection
from anki.scheduler.v3 import CardAnswer
from apkg import collection_bytes, fresh_collection, open_db, packages


@pytest.mark.claim("APKG-CARD-001")
def test_new_card_due_is_queue_position(conformance: Path) -> None:
    for case, _, package in packages(conformance):
        with open_db(collection_bytes(package)) as db:
            position = {
                nid: rank
                for rank, (nid,) in enumerate(db.execute("select id from notes order by id"), 1)
            }
            new = db.execute("select nid, due from cards where type = 0").fetchall()
        assert new, case
        # Siblings share their note's position.
        for nid, due in new:
            assert due == position[nid], case


def _answer(col: Collection, rating: CardAnswer.Rating.V) -> int:
    queued = col.sched.get_queued_cards(fetch_limit=1).cards[0]
    card = col.get_card(queued.card.id)
    card.start_timer()
    col.sched.answer_card(col.sched.build_answer(card=card, states=queued.states, rating=rating))
    return card.id


@pytest.mark.claim("APKG-CARD-002")
def test_queue_values() -> None:
    with fresh_collection() as col:
        conf = col.decks.config_dict_for_deck_id(1)
        conf["new"]["delays"] = [1, 1440]
        conf["new"]["bury"] = True
        col.decks.save(conf)

        def add(notetype: str, fields: list[str]) -> list[int]:
            note = col.new_note(col.models.by_name(notetype))
            note.fields = fields
            col.add_note(note, 1)
            return [c.id for c in note.cards()]

        reversed_pair = add("Basic (and reversed card)", ["a", "b"])
        suspended, manual, new = (add("Basic", [f"{i}", "x"])[0] for i in range(3))
        review = add("Basic", ["r", "x"])[0]
        col.sched.suspend_cards([suspended])
        col.sched.bury_cards([manual], manual=True)
        col.sched.set_due_date([review], "3")

        learning = _answer(col, CardAnswer.AGAIN)
        assert learning == reversed_pair[0]
        sibling = reversed_pair[1]

        def queue(cid: int) -> int:
            return col.db.scalar("select queue from cards where id = ?", cid)

        assert queue(manual) == -3
        assert queue(sibling) == -2
        assert queue(suspended) == -1
        assert queue(new) == 0
        assert queue(learning) == 1
        assert queue(review) == 2

        # Good on the first step moves to the one-day step: learning counted in days.
        col.db.execute("update cards set due = 0 where id = ?", learning)
        assert _answer(col, CardAnswer.GOOD) == learning
        assert queue(learning) == 3
