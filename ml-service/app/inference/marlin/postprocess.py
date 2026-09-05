"""Turn Marlin's timed English captions into Boundr manipulation segments."""

from __future__ import annotations

import re
from functools import cache, lru_cache
from typing import Callable

from app.inference.base import JobContext, make_segment

Postprocessor = Callable[[str, float, JobContext], list[dict]]

EVENT_RE = re.compile(
    r"^\s*<?\s*(\d+\.?\d*)\s*(?:seconds?|secs?|s)?\s*-\s*"
    r"(\d+\.?\d*)\s*(?:seconds?|secs?|s)?\s*>?\s*[:\-]?\s*(.+?)\s*$",
    re.I | re.M,
)
ACTOR_WORDS = {
    "arm", "chef", "cook", "gripper", "hand", "he", "human", "i", "individual",
    "man", "operator", "person", "robot", "she", "somebody", "someone",
    "they", "user", "we", "wearer", "woman", "worker", "you",
}
BODY_WORDS = ACTOR_WORDS | {"body", "face", "finger", "head"}
# ponytail: syntax cannot prove physical contact; use a project action catalog
# when open-vocabulary precision matters.
NON_MANIPULATION = {
    "access", "approach", "be", "belong", "check", "enter", "examine",
    "face", "fail", "finish", "gesture", "go", "have", "head", "inspect", "intend",
    "know", "leave", "look", "need", "nod", "observe", "own", "plan", "point",
    "pause", "prepare", "remain", "remember", "resume", "reveal", "say",
    "search", "see", "seem", "show", "sit", "stand", "stare", "wait", "walk",
    "want", "watch", "wave", "wear",
}
REQUIRE_DIRECT_OBJECT = {
    "hover", "lean", "move", "rest", "retract", "return", "smile", "speak",
    "talk", "turn",
}
TRANSPARENT_COMPLEMENT_HEADS = {
    "attempt", "begin", "continue", "see", "start", "try", "use",
}
NON_ACTUALIZING_HEADS = {"fail", "intend", "pause", "plan", "prepare", "want"}
NEGATION_BREAKERS = {
    "afterward", "afterwards", "but", "however", "instead", "then", "yet",
}
SEQUENCE_BREAKERS = {"afterward", "afterwards", "then"}
SPACY_LEMMA_FIXES = {"instal": "install", "reattache": "reattach"}
CATALOG_ACTION_FIXES = {
    "flip_over": "flip",
    "hold_up": "hold",
    "press_down": "press",
    "pull_out": "pick_up",
}
ACTION_EQUIVALENTS = (
    ("adjust", "arrange"),
    ("attach", "reattach"),
    ("clean", "wash", "wipe"),
    ("close", "shut"),
    ("cut", "slice"),
    ("grab", "hold", "carry"),
    ("open", "pull_open"),
    ("pick_up", "take", "retrieve", "lift", "remove", "pull"),
    ("put", "put_down", "place", "set", "set_down"),
    (
        "reach", "reach_for", "reach_in", "reach_into", "reach_out",
        "reach_toward", "reach_towards",
    ),
)


@cache
def _english():
    import spacy

    return spacy.load("en_core_web_sm", exclude=["ner"])


def _normalized(value: str) -> str:
    return "_".join(value.lower().replace("-", " ").replace("_", " ").split())


@lru_cache(maxsize=256)
def _lemmatized(value: str) -> str:
    doc = _english()(_normalized(value).replace("_", " "))
    return _normalized(" ".join(token.lemma_ for token in doc if not token.is_punct))


@lru_cache(maxsize=256)
def _action_lemma(value: str) -> str:
    if value.lower().endswith("ing"):
        contextual = _english()(f"They are {value}.")
        lemma = next(
            (token.lemma_.lower() for token in contextual if token.pos_ == "VERB"),
            None,
        )
        if lemma is not None:
            return lemma
    return _lemmatized(value)


@lru_cache(maxsize=256)
def _contextual_verb(text: str, offset: int, surface: str, lemma: str) -> bool:
    """Retry an ambiguous plural noun as its lemma in the same sentence."""
    rewritten = text[:offset] + lemma + text[offset + len(surface):]
    return any(
        token.idx == offset and token.pos_ == "VERB"
        for token in _english()(rewritten)
    )


def _catalog_action(value: str, catalog: list[str]) -> str | None:
    if not catalog:
        return value
    normalized = _normalized(value)
    labels = [(label, _normalized(label), _lemmatized(label)) for label in catalog]
    for label, spelling, _ in labels:
        if spelling == normalized:
            return label
    for label, _, lemma in labels:
        if lemma == normalized:
            return label
    normalized = CATALOG_ACTION_FIXES.get(normalized, normalized)
    for label, spelling, lemma in labels:
        if spelling == normalized or lemma == normalized:
            return label
    equivalents = next(
        (group for group in ACTION_EQUIVALENTS if normalized in group), ()
    )
    for alias in equivalents:
        for label, spelling, lemma in labels:
            if spelling == alias or lemma == alias:
                return label
    return None


def _catalog_object(value: str, lemmas: str, catalog: list[str]) -> str | None:
    if not catalog:
        return value
    haystacks = {
        _normalized(value).replace("_", " "),
        _normalized(lemmas).replace("_", " "),
    }
    for label in sorted(catalog, key=len, reverse=True):
        needles = {
            _normalized(label).replace("_", " "),
            _lemmatized(label).replace("_", " "),
        }
        if any(
            f" {needle} " in f" {haystack} "
            for needle in needles
            for haystack in haystacks
        ):
            return label
    return None


def _actor_nominal(token) -> bool:
    return token.lemma_.lower() in ACTOR_WORDS or any(
        child.dep_ == "conj" and _actor_nominal(child) for child in token.children
    )


def _predicate_ancestor(token):
    current = token.head
    while True:
        if current.pos_ == "VERB":
            return current
        if current.i == current.head.i:
            return None
        current = current.head


def _breaks_shared_scope(token) -> bool:
    if token.i == token.head.i:
        return False
    left, right = sorted((token.i, token.head.i))
    return any(
        child.lemma_.lower() in NEGATION_BREAKERS
        and (child.lemma_.lower() not in SEQUENCE_BREAKERS or token.tag_ != "VB")
        for child in (*token.children, *token.head.children)
        if child.head.i == token.i or left < child.i < right
    )


def _has_actor(verb) -> bool:
    current = verb
    if verb.pos_ != "VERB" and verb.dep_ != "ROOT":
        current = _predicate_ancestor(verb) or verb.head
    while True:
        agents = [child for child in current.children if child.dep_ == "agent"]
        if any(
            _actor_nominal(part)
            for agent in agents
            for part in agent.children
            if part.dep_ == "pobj"
        ):
            return True
        subjects = [
            child for child in current.children if child.dep_ in {"csubj", "nsubj"}
        ]
        if subjects:
            return any(_actor_nominal(subject) for subject in subjects)
        if any(
            child.dep_ == "compound" and _actor_nominal(child)
            for child in current.children
        ):
            return True
        passive_subjects = [
            child for child in current.children if child.dep_ == "nsubjpass"
        ]
        if current.i != verb.i and passive_subjects:
            return any(_actor_nominal(subject) for subject in passive_subjects)
        if (
            current.dep_ == "ROOT"
            and current.pos_ == "VERB"
            and current.i == current.sent.start
            and not passive_subjects
        ):
            return True  # Marlin occasionally emits imperative event captions.
        if current.dep_ == "dep" and _breaks_shared_scope(current):
            current = current.head
            continue
        if current.dep_ not in {"acomp", "advcl", "conj", "xcomp"}:
            return False
        current = current.head


def _is_predicate(token) -> bool:
    if token.pos_ == "VERB":
        # en_core_web_sm occasionally reads the second noun in "X and Y" as
        # an infinitive. A finite singular head cannot coordinate that form.
        if token.dep_ == "conj" and token.tag_ == "VB" and token.head.tag_ == "VBZ":
            return False
        return True
    if token.tag_ != "NNS" or token.dep_ not in {"ROOT", "conj"}:
        return False
    if token.dep_ == "conj":
        sentence = token.sent
        return _is_predicate(token.head) or _contextual_verb(
            sentence.text,
            token.idx - sentence.start_char,
            token.text,
            token.lemma_,
        )
    return any(
        child.dep_ in {"compound", "csubj", "nsubj"} and _actor_nominal(child)
        for child in token.children
    )


def _governing_predicate(token):
    return token.head if _is_predicate(token.head) else _predicate_ancestor(token)


def _actor_predicate(token) -> bool:
    return _is_predicate(token) and _has_actor(token)


def _is_negated(verb) -> bool:
    current = verb
    while True:
        if any(child.dep_ == "neg" for child in current.children):
            return True
        if _breaks_shared_scope(current):
            return False
        if current.dep_ not in {"acomp", "advcl", "ccomp", "conj", "xcomp"}:
            return False
        current = current.head


def _direct_object(verb):
    dependencies = {"dobj", "nsubjpass"}
    if verb.pos_ != "VERB":
        dependencies.add("npadvmod")
    direct = next(
        (child for child in verb.children if child.dep_ in dependencies),
        None,
    )
    if direct is None:
        return None
    # In "secures the card and checks cables", the small model can attach
    # "card" as a modifier of "cables" while still finding the second verb.
    return next(
        (
            child
            for child in direct.children
            if child.dep_ == "nmod"
            and child.i < direct.i
            and any(
                sibling.dep_ == "conj"
                and (
                    _is_predicate(sibling)
                    or sibling.lemma_.lower() in NON_MANIPULATION
                )
                for sibling in child.children
            )
        ),
        direct,
    )


def _complement_object(verb):
    for complement in verb.children:
        if complement.dep_ not in {"acomp", "ccomp", "oprd"}:
            continue
        # "pry the can open" may be read as determiner + auxiliary + verb.
        auxiliary = next(
            (
                child
                for child in complement.children
                if child.dep_ in {"aux", "compound"}
                and child.pos_ == "AUX"
                and (
                    any(part.dep_ == "det" for part in child.children)
                    or any(
                        part.dep_ in {"nsubj", "nsubjpass"} and part.tag_ == "DT"
                        for part in complement.children
                    )
                )
            ),
            None,
        )
        if auxiliary is not None:
            return auxiliary
        if complement.pos_ in {"NOUN", "PROPN"}:
            return complement
        subject = next(
            (
                child
                for child in complement.children
                if child.dep_ in {"nsubj", "nsubjpass"}
                and not _actor_nominal(child)
            ),
            None,
        )
        if subject is not None:
            # A finite complement with a non-human subject is commonly a
            # plural object mis-tagged as a verb ("Joy-Con controls").
            return complement if complement.pos_ == "VERB" else subject
    return None


def _prepositional_object(verb):
    for prep in verb.children:
        if prep.dep_ != "prep" or prep.lemma_.lower() in {
            "by", "from", "using", "with",
        }:
            continue
        target = next((child for child in prep.children if child.dep_ == "pobj"), None)
        if target is None:
            continue
        # "reach into the refrigerator for onions" targets the onions.
        purpose = next(
            (
                child
                for child in target.children
                if child.dep_ == "prep" and child.lemma_.lower() == "for"
            ),
            None,
        )
        if purpose is not None:
            target = next(
                (child for child in purpose.children if child.dep_ == "pobj"),
                target,
            )
        return target
    return None


def _object_for(verb):
    direct = _direct_object(verb)
    if direct is not None:
        if (
            direct.lemma_.lower() in {"it", "them"}
            and verb.dep_ == "conj"
            and _is_predicate(verb.head)
        ):
            antecedent = next(
                (
                    candidate
                    for candidate in (
                        _direct_object(verb.head),
                        _prepositional_object(verb.head),
                        _complement_object(verb.head),
                    )
                    if candidate is not None
                ),
                None,
            )
            if antecedent is not None:
                direct = antecedent
        return direct, True

    complement = _complement_object(verb)
    if complement is not None:
        return complement, True

    prep = _prepositional_object(verb)
    if verb.lemma_.lower() == "reach" and prep is not None:
        return prep, False
    if (
        verb.lemma_.lower() == "turn"
        and prep is not None
        and any(
            child.dep_ == "prep" and child.lemma_.lower() in {"on", "off"}
            for child in verb.children
        )
    ):
        return prep, True

    # The small parser sometimes labels a coordinated finite verb as NNS and
    # leaves its local object unattached ("opens a cabinet and grabs a bowl").
    if verb.pos_ != "VERB" and verb.dep_ == "conj":
        for token in verb.doc[verb.i + 1:verb.sent.end]:
            if (
                token.pos_ not in {"NOUN", "PROPN", "PRON"}
                or _actor_nominal(token)
                or _is_predicate(token)
            ):
                continue
            between = verb.doc[verb.i + 1:token.i]
            if any(
                part.is_punct
                or part.pos_ in {"ADP", "SCONJ"}
                or part.dep_ == "mark"
                or _actor_predicate(part)
                for part in between
            ):
                break
            return token, True

    if verb.lemma_.lower() == "turn" and any(
        child.dep_ == "prt" and child.lemma_.lower() in {"on", "off"}
        for child in verb.children
    ):
        target = next(
            (chunk.root for chunk in verb.doc.noun_chunks if chunk.root.i > verb.i),
            None,
        )
        if target is not None:
            return target, True

    # Recover pronouns that the small English model attaches to a direction
    # word in coordinated phrases such as "lifts the bowl and moves it right".
    if verb.dep_ == "conj":
        head = _governing_predicate(verb)
        antecedent = _direct_object(head) if head is not None else None
        if antecedent is not None:
            local_pronoun = any(
                token.lemma_.lower() in {"it", "them"} and token.dep_ == "nsubj"
                for token in verb.subtree
            )
            return antecedent, local_pronoun

    # English coordination sometimes puts the shared object on the later verb.
    for child in verb.children:
        if child.dep_ == "conj" and _is_predicate(child):
            direct = _direct_object(child)
            if direct is not None:
                return direct, False

    if prep is not None:
        return prep, False

    for chunk in verb.doc.noun_chunks:
        if chunk.root.i > verb.i and not _actor_nominal(chunk.root):
            return chunk.root, False
    return None


def _object_values(root) -> tuple[str, str]:
    selected = []

    def collect(token) -> None:
        left, right = sorted((token.i, root.i))
        if token.i != root.i and (
            _actor_predicate(token)
            or any(_actor_predicate(part) for part in root.doc[left + 1:right])
        ):
            return
        if token.dep_ not in {"det", "prt"} and token.pos_ != "ADV" and (
            token.dep_ != "punct" or token.text == "-"
        ):
            selected.append(token)
        for child in token.children:
            if child.dep_ in {"acl", "advcl", "relcl"} or child.pos_ == "ADV":
                continue
            if child.dep_ in {"csubj", "nsubj"} and child.pos_ == "VERB":
                continue
            if child.dep_ == "prep" and child.lemma_.lower() != "of":
                continue
            collect(child)

    collect(root)
    # Recover a coordinated noun mis-tagged as a bare verb ("the cup and
    # bottle") without absorbing its destination phrase.
    if root.dep_ == "dobj":
        mistagged = next(
            (
                sibling
                for sibling in root.head.children
                if sibling.dep_ == "conj"
                and sibling.pos_ == "VERB"
                and sibling.tag_ == "VB"
                and any(
                    token.dep_ == "cc"
                    for token in root.doc[root.right_edge.i + 1:sibling.i]
                )
                and not any(
                    child.dep_ in {"csubj", "nsubj", "nsubjpass"}
                    for child in sibling.children
                )
            ),
            None,
        )
        if mistagged is not None:
            selected.append(next(
                token for token in root.doc[root.right_edge.i + 1:mistagged.i]
                if token.dep_ == "cc"
            ))
            collect(mistagged)
    # Recover a trailing plural product noun mis-tagged as a finite ccomp,
    # while keeping its destination preposition out of the object phrase.
    if root.pos_ == "PROPN" and root.dep_ == "dobj":
        trailing = next(
            (
                sibling
                for sibling in root.head.children
                if sibling.dep_ == "ccomp"
                and sibling.pos_ == "VERB"
                and sibling.tag_ == "VBZ"
                and sibling.i == root.right_edge.i + 1
                and not any(
                    child.dep_ in {"csubj", "nsubj", "nsubjpass"}
                    for child in sibling.children
                )
            ),
            None,
        )
        if trailing is not None:
            collect(trailing)
    selected.sort(key=lambda token: token.i)
    while selected and selected[-1].pos_ == "CCONJ":
        selected.pop()
    text = "".join(token.text_with_ws for token in selected).strip(" .,:;\"'")
    lemmas = " ".join(token.lemma_.lower() for token in selected)
    return text, lemmas


def _manipulations(doc) -> list[tuple[str, str, str]]:
    candidates = []
    for verb in doc:
        if not _actor_predicate(verb) or _is_negated(verb):
            continue
        found = _object_for(verb)
        if found is None:
            continue
        obj, direct = found
        lemma = verb.lemma_.lower()
        lemma = SPACY_LEMMA_FIXES.get(lemma, lemma)
        object_lemma = obj.lemma_.lower()
        light_verb = lemma in {"do", "make", "perform"}
        if light_verb:
            target = next(
                (
                    child
                    for prep in (*obj.children, *verb.children)
                    if prep.dep_ == "prep" and prep.lemma_.lower() in {"of", "on"}
                    for child in prep.children
                    if child.dep_ == "pobj"
                ),
                None,
            )
            if target is not None and object_lemma not in NON_MANIPULATION:
                candidates.append((verb, _action_lemma(object_lemma), target))
                continue
        if lemma == "finish" and obj.text.lower().endswith("ing"):
            concrete = next(
                (
                    _direct_object(child)
                    for child in verb.children
                    if child.dep_ == "conj" and _is_predicate(child)
                    and _direct_object(child) is not None
                ),
                None,
            )
            if concrete is not None:
                candidates.append((verb, _action_lemma(obj.text), concrete))
        if (
            object_lemma in BODY_WORDS
            or lemma in NON_MANIPULATION
            or (lemma == "reach" and direct)
            or (light_verb and object_lemma in NON_MANIPULATION)
            or (not direct and lemma in REQUIRE_DIRECT_OBJECT)
        ):
            continue
        particles = [
            child.lemma_.lower() for child in verb.children if child.dep_ == "prt"
        ]
        particles += [
            child.lemma_.lower()
            for child in verb.children
            if child.dep_ in {"acomp", "ccomp", "oprd"}
            and child.pos_ in {"ADP", "ADV"}
            and child.lemma_.lower() in {"aside", "back", "down", "up"}
        ]
        if obj.pos_ == "VERB" and obj.dep_ in {"acomp", "ccomp", "oprd"}:
            particles += [
                child.lemma_.lower() for child in obj.children if child.dep_ == "prt"
            ]
        if lemma == "turn":
            particles += [
                child.lemma_.lower()
                for child in verb.children
                if child.dep_ == "prep" and child.lemma_.lower() in {"on", "off"}
            ]
        result_open = any(
            child.dep_ in {"acomp", "advcl", "ccomp", "oprd"}
            and child.lemma_.lower() == "open"
            and not any(
                marker.dep_ in {"aux", "mark"} and marker.lemma_.lower() == "to"
                for marker in child.children
            )
            for child in verb.children
        )
        action = (
            "open"
            if lemma == "pull" and result_open
            else "_".join([lemma, *particles])
        )
        candidates.append((verb, action, obj))

    # Prefer concrete complements in "begins to cut" or "uses scissors to cut",
    # but not result clauses such as "presses a button to start the machine".
    candidate_ids = {verb.i for verb, _, _ in candidates}
    complement_dependencies = {"advcl", "ccomp", "xcomp"}
    shadowed = {
        verb.head.i
        for verb, _, _ in candidates
        if verb.dep_ in complement_dependencies
        and verb.head.i in candidate_ids
        and verb.head.lemma_.lower() in TRANSPARENT_COMPLEMENT_HEADS
    }
    parsed = []
    for verb, action, obj in candidates:
        if verb.i in shadowed:
            continue
        if verb.dep_ in complement_dependencies:
            head_lemma = verb.head.lemma_.lower()
            if head_lemma in NON_ACTUALIZING_HEADS:
                continue
            if (
                verb.head.i in candidate_ids
                and head_lemma not in TRANSPARENT_COMPLEMENT_HEADS
                and head_lemma != "reach"
            ):
                continue
        if (
            verb.dep_ == "advcl"
            and verb.head.lemma_.lower() not in TRANSPARENT_COMPLEMENT_HEADS
            and any(
                child.dep_ in {"aux", "mark"} and child.lemma_.lower() == "to"
                for child in verb.children
            )
        ):
            continue
        value, lemmas = _object_values(obj)
        if value:
            parsed.append((action, value, lemmas))
    return parsed


def parse_manipulations(text: str, duration: float, ctx: JobContext) -> list[dict]:
    events = list(EVENT_RE.finditer(text))
    if not events:
        raise ValueError("Marlin response did not contain timed events")
    segments = []
    descriptions = [event.group(3) for event in events]
    for event, doc in zip(events, _english().pipe(descriptions)):
        start = max(0.0, min(float(event.group(1)), duration))
        end = max(start, min(float(event.group(2)), duration))
        if end <= start:
            continue
        seen = set()
        for raw_action, raw_object, object_lemmas in _manipulations(doc):
            action = _catalog_action(raw_action, ctx.action_types or [])
            obj = _catalog_object(raw_object, object_lemmas, ctx.objects or [])
            if not action or not obj or (action, obj) in seen:
                continue
            seen.add((action, obj))
            segments.append(make_segment(start, end, action, obj))
    return segments


if __name__ == "__main__":
    ctx = JobContext("self-check", "video", "")
    parsed = parse_manipulations(
        "<0 - 2> The camera pans across the counter.\n"
        "<2 - 4> A hand opens a lower cabinet door.\n"
        "<4 - 6> The person puts a cup down and turns off the stove.\n"
        "<6 - 8> A drawer is closed by a worker.",
        8,
        ctx,
    )
    assert [
        (item["start"], item["end"], item["action"], item["object"])
        for item in parsed
    ] == [
        (2.0, 4.0, "open", "lower cabinet door"),
        (4.0, 6.0, "put_down", "cup"),
        (4.0, 6.0, "turn_off", "stove"),
        (6.0, 8.0, "close", "drawer"),
    ]
    assert [item["keyframe"] for item in parsed] == [2.8, 4.8, 4.8, 6.8]

    cataloged = parse_manipulations(
        "0-1 A hand pulls out a card.",
        1,
        JobContext(
            "self-check", "video", "", action_types=["pick_up"], objects=["card"]
        ),
    )
    assert [(item["action"], item["object"]) for item in cataloged] == [
        ("pick_up", "card"),
    ]
    assert _catalog_action("place", ["put"]) == "put"
    assert _catalog_action("pick_up", ["picks up"]) == "picks up"
    assert _catalog_action("cut", ["cutting"]) == "cutting"
    try:
        parse_manipulations("Scene: a quiet room.", 2, ctx)
    except ValueError:
        pass
    else:
        raise AssertionError("untimed captions must fail")
    print("ok")
