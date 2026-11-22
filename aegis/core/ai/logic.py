"""Propositional logic for the rule base: resolution proofs and backward-chaining explanations.

The runtime rule engine (`ai/rules.py`) is forward chaining over Python functions. This module
states the same rules as propositional Horn clauses, so that two things can be checked:

* resolution refutation proves whether a rule fires for a given set of facts (a proof method
  independent of the Python code), and
* backward chaining explains *why* a rule fires, as a chain of facts.

Literals are strings. "~X" is the negation of "X". A Horn rule is (head, body), where body is a
list of literals; a negated body literal is negation-as-failure: it holds when X is not a fact.
Facts are a closed world: anything not listed is false.
"""

# The propositional form of ai/rules.py. Each rule name is the head; the body is what must hold.
RULE_CLAUSES = [
    ("fire_at_fuel_depot", ["Fire", "FuelDepot"]),
    ("medical_at_hospital", ["Medical", "Hospital"]),
    ("mass_casualty", ["People100"]),
    ("crowded_tourist_hub", ["Accident", "TouristHub", "~People60"]),
]

MAX_CLAUSES = 20000     # resolution gives up after this many clauses (propositional, so rare)


def neg(lit):
    return lit[1:] if lit.startswith("~") else "~" + lit


def horn_to_clause(head, body):
    """(head, body) -> the equivalent disjunction: head OR NOT(each body literal)."""
    return frozenset([head] + [neg(b) for b in body])


def resolve(c1, c2):
    """All resolvents of two clauses (frozensets of literals)."""
    out = []
    for lit in c1:
        if neg(lit) in c2:
            out.append(frozenset((c1 - {lit}) | (c2 - {neg(lit)})))
    return out


def refute(clauses, goal):
    """Does the clause set entail `goal`? Resolution refutation: add NOT goal and look for the
    empty clause. Returns (entailed, number_of_clauses)."""
    clauses = {frozenset(c) for c in clauses}
    clauses.add(frozenset([neg(goal)]))
    while True:
        new = set()
        items = list(clauses)
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                for r in resolve(a, b):
                    if not r:
                        return True, len(clauses)
                    new.add(r)
        if new <= clauses:
            return False, len(clauses)
        clauses |= new
        if len(clauses) > MAX_CLAUSES:
            raise RuntimeError("resolution did not finish; the clause set is too large")


def kb_clauses(facts, facts_universe, rules=RULE_CLAUSES):
    """Knowledge base for one situation: every rule as a clause, plus a unit clause per fact.
    Facts in `facts_universe` but not in `facts` become negative unit clauses (closed world)."""
    clauses = [horn_to_clause(h, b) for h, b in rules]
    clauses += [frozenset([f]) for f in facts]
    clauses += [frozenset(["~" + f]) for f in facts_universe if f not in facts]
    return clauses


def prove(goal, facts, rules=RULE_CLAUSES, depth=0):
    """Backward chaining. Returns the proof as a list of lines (leaves first), or None.
    A goal is proved if it is a fact, or some rule with that head has a provable body
    (negated literals are proved by absence from the facts)."""
    if depth > 20:
        return None
    if goal in facts:
        return [f"{goal}: given"]
    for head, body in rules:
        if head != goal:
            continue
        lines = []
        for lit in body:
            if lit.startswith("~"):
                if lit[1:] in facts:
                    break
                lines.append(f"{lit}: not a fact (negation as failure)")
            else:
                sub = prove(lit, facts, rules, depth + 1)
                if sub is None:
                    break
                lines += sub
        else:
            return lines + [f"{goal} because {' and '.join(body)}"]
    return None


def explain(facts, rules=RULE_CLAUSES):
    """For each rule, the proof it fires, or None when it does not. Used by the CLI."""
    return {head: prove(head, set(facts), rules) for head, _ in rules}


TAG_FACTS = {"fuel_depot": "FuelDepot", "hospital": "Hospital", "tourist_hub": "TouristHub"}
TYPE_FACTS = {"Fire": "Fire", "Medical": "Medical", "Accident": "Accident"}


def incident_facts(incident_type, tags, people):
    """Map an incident and its city's facility tags to the propositional facts above."""
    facts = {TYPE_FACTS[incident_type]} if incident_type in TYPE_FACTS else set()
    facts |= {TAG_FACTS[t] for t in tags if t in TAG_FACTS}
    if people >= 100:
        facts.add("People100")
    if people >= 60:
        facts.add("People60")
    return facts
