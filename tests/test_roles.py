"""Roles from metadata, and decision cues."""

from __future__ import annotations

from decrack.models import Post, Thread
from decrack.pipeline.roles import assign_roles, cue_score


def post(seq: int, author: str, role: str = "unknown", **meta) -> Post:
    """The post at place ``seq`` of its thread; roles never depend on what a post says."""
    return Post(id=f"x:{seq}", seq=seq, author=author, role=role, meta=meta)


def roles(thread: Thread) -> list[str]:
    return [item.role for item in assign_roles(thread).posts]


# Roles


def test_discourse_roles():
    thread = Thread(
        id="dpo:t1",
        kind="discourse",
        meta={"created_by": ["Alice", "carol"], "pep_authors": ["Bob  Builder"]},
        posts=[
            post(1, "alice", username="alice"),
            post(2, "bobb", username="bobb", name="  bob builder "),
            post(3, "sam", username="sam", flair_name="Steering-Council"),
            post(4, "tess", username="tess", user_title="Steering Council member"),
            post(5, "dave", username="dave", primary_group_name="committers"),
            post(6, "eve", username="eve", user_title="CPython Core Developer"),
            post(7, "frank", username="frank"),
            post(8, "gina", role="decider", username="gina"),
            # A PEP author on the Steering Council stays the author of their own PEP.
            post(9, "carol", username="carol", flair_name="steering-council", primary_group_name="committers"),
        ],
    )
    expected = [
        "author",
        "author",
        "decider",
        "decider",
        "maintainer",
        "maintainer",
        "participant",
        "decider",
        "author",
    ]
    assert roles(thread) == expected
    assert roles(thread) == expected  # idempotent


def test_synthetic_thread_roles_come_back_from_metadata(synthetic_thread):
    expected = [item.role for item in synthetic_thread.posts]
    for item in synthetic_thread.posts:
        item.role = "unknown"
    assert roles(synthetic_thread) == expected
    assert expected == [
        "author",
        "participant",
        "participant",
        "maintainer",
        "author",
        "participant",
        "participant",
        "decider",
    ]


def test_github_roles():
    thread = Thread(
        id="gh:o/r#1",
        kind="github_pr",
        meta={"opener": "octo", "merged_by": "Mona", "closed_by": None},
        posts=[
            post(1, "octo", author_association="CONTRIBUTOR"),
            post(2, "mona", author_association="MEMBER"),
            post(3, "hubot", author_association="COLLABORATOR"),
            post(4, "randy", author_association="NONE"),
            post(5, "mona", author_association="MEMBER"),
            post(6, "lee", role="participant", author_association="OWNER"),
        ],
    )
    assert roles(thread) == ["author", "decider", "maintainer", "participant", "decider", "participant"]


def test_github_owner_who_opens_and_closes_stays_the_author():
    # Opening, proposing and closing your own issue is not an independent decision.
    thread = Thread(
        id="gh:o/r#2",
        kind="github_issue",
        meta={"opener": "lead", "closed_by": {"login": "lead"}, "state_reason": "not_planned"},
        posts=[post(1, "lead", author_association="OWNER"), post(2, "newbie", author_association="NONE")],
    )
    assert roles(thread) == ["author", "participant"]


def test_github_decider_is_the_member_who_closed_it():
    thread = Thread(
        id="gh:o/r#6",
        kind="github_issue",
        meta={"opener": "lead", "closed_by": "maint"},
        posts=[
            post(1, "lead", author_association="OWNER"),
            post(2, "maint", author_association="MEMBER"),
            post(3, "other", author_association="MEMBER"),
        ],
    )
    assert roles(thread) == ["author", "decider", "maintainer"]


def test_github_closer_without_rights_stays_author():
    thread = Thread(
        id="gh:o/r#3",
        kind="github_issue",
        meta={"opener": "newbie", "closed_by": "newbie"},
        posts=[post(1, "newbie", author_association="NONE"), post(2, "maint", author_association="MEMBER")],
    )
    assert roles(thread) == ["author", "maintainer"]


def test_github_opener_defaults_to_the_first_post():
    thread = Thread(
        id="gh:o/r#4",
        kind="github_issue",
        posts=[post(1, "zed", author_association="NONE"), post(2, "amy", author_association="NONE")],
    )
    assert roles(thread) == ["author", "participant"]

    # The first post is the one with the lowest seq, wherever it sits in the list.
    shuffled = Thread(
        id="gh:o/r#5",
        kind="github_issue",
        posts=[post(2, "amy", author_association="NONE"), post(1, "zed", author_association="NONE")],
    )
    assert roles(shuffled) == ["participant", "author"]


def test_file_roles():
    thread = Thread(id="file:notes", kind="file", posts=[post(1, "x"), post(2, "y"), post(3, "x")])
    assert roles(thread) == ["author", "participant", "author"]

    shuffled = Thread(id="file:shuffled", kind="file", posts=[post(3, "x"), post(1, "y"), post(2, "x")])
    assert roles(shuffled) == ["participant", "author", "participant"]

    created = Thread(
        id="file:other",
        kind="file",
        meta={"created_by": ["y"]},
        posts=[post(1, "x"), post(2, "y", role="maintainer"), post(3, "Y")],
    )
    assert roles(created) == ["participant", "maintainer", "author"]


def test_posts_without_a_real_name_never_become_authors():
    plain_file = Thread(id="file:plain", kind="file", posts=[post(1, "unknown"), post(2, "unknown"), post(3, "")])
    assert roles(plain_file) == ["participant", "participant", "participant"]

    forum = Thread(
        id="dpo:t2",
        kind="discourse",
        meta={"created_by": ["unknown", ""]},
        posts=[post(1, "unknown", username="unknown"), post(2, "")],
    )
    assert roles(forum) == ["participant", "participant"]


# Cues


def test_cue_score():
    assert cue_score("Why not use a decorator instead of a new keyword?") == 2
    assert cue_score("This was added to Rejected Ideas, so -1 from me and we won't do it.") == 3
    assert cue_score("That is out of scope for now, so let's defer it; I added it to the PEP.") == 3
    assert cue_score("Alternatively, we will not withdraw it.") == 3
    assert cue_score("We're not going to do that.") == 1
    assert cue_score("We rejected the decorator approach.") == 1
    assert cue_score("Thanks for all the ideas. Use n-1 workers.") == 0
    assert cue_score("") == 0
