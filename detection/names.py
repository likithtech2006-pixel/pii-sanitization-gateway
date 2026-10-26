"""Person-name detection.

Names are found in two stages, both over the WHOLE document:

1. Discovery - candidate names come from
     * spaCy NER (PERSON entities), when spaCy and a model are installed;
     * context cues: "Led by X", "owned by X", "Owner: X", "Dear X", "X (EMP-40077)";
     * table columns whose header says Name / Users / Owner / Contact ...;
     * document properties (author, last_modified_by);
     * lines that look like a name AND are corroborated by an e-mail address
       in the document (m.vossberg@... corroborates "Marguerite Vossberg").
   Each candidate gets a confidence from its evidence; candidates made of
   ordinary words ("Trigger Type", "Risk Owner", "Vendor Created") are rejected
   with a business-vocabulary stop list and a document-specific check (a word
   that also appears in lower case in the same document is a common word).

2. Propagation - every accepted person is then searched for in every block in
   all common surface forms: "Naomi K. Osadebe", "Naomi Osadebe", "N. Osadebe",
   "N.K. Osadebe", "Osadebe, Naomi", "NAOMI OSADEBE", and the bare surname when
   it is distinctive. All forms share one entity key, so the redactor gives them
   the same placeholder ([PERSON_3]) and the sanitized text stays coherent.

OCR text from pictures/screenshots is noisy, so NER alone never creates a name
there; such blocks only receive names already confirmed elsewhere or via cues.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from detection.lexicon import GIVEN_NAMES

# ------------------------------------------------------------------ name shape
UP = "A-ZÀ-ÖØ-ÞĀĂĄĆĈĊČĎĐĒĔĖĘĚĜĞĠĢĤĦĨĪĬĮİĲĴĶĹĻĽĿŁŃŅŇŊŌŎŐŒŔŖŘŚŜŞŠŢŤŦŨŪŬŮŰŲŴŶŸŹŻŽ"
LO = "a-zß-öø-ÿāăąćĉċčďđēĕėęěĝğġģĥħĩīĭįıĳĵķĺļľŀłńņňŋōŏőœŕŗřśŝşšţťŧũūŭůűųŵŷźżž"
WORD = rf"[{UP}][{LO}]+(?:['’][{UP}]?[{LO}]+)?(?:-[{UP}][{LO}]+)*"   # Osadebe, O'Neil, Okonkwo-Bell
MAC = rf"(?:Mc|Mac|De|Van|Von|Le|La|Di|Du|Da|Al|El)[{UP}][{LO}]+"   # McDonald, DeSouza
INITIAL = rf"[{UP}]\.(?: ?-?[{UP}]\.)?"                                # K.  L.-E.  N.K.
PAIR_INITIALS = rf"[{UP}]{{2}}"                                         # KC, DK (first token only)
PARTICLE = r"(?:van der|van den|van|von|de la|de|del|della|da|di|du|le|la|bin|al|el|ibn)"
TOKEN = rf"(?:{MAC}|{WORD})"

# First Last | First M. Last | F. Last | JT Harrow | Anna van der Berg
NAME_RE = re.compile(
    rf"(?<![\w@.])(?:{TOKEN}|{INITIAL}|{PAIR_INITIALS})"
    rf"(?:[ \t](?:{INITIAL} ?)?(?:{PARTICLE} )?{TOKEN}){{1,7}}(?![\w@])"
)
LINE_NAME_RE = re.compile(rf"^[ \t]*(?:(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.? )?({NAME_RE.pattern})[ \t]*[,;:]?[ \t]*$")

TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "dame", "madam"}

# Words that never form part of a personal name in business documents.
STOP = set("""
a an the and or of for to in on at by with from as is are be this that these those it its our your their
group team teams committee board office division department unit function service services company corporation
corp inc ltd limited llc plc pte sa ag gmbh bank capital partners partner holdings financial finance cadence
chief officer officers executive director directors manager managers head lead vp president vice chair chairman
chairperson counsel general secretary treasurer controller analyst engineer engineering administrator admin
owner owners holder holders contact contacts user users approver approvers reviewer reviewers member members
risk risks compliance security privacy data information technology operations operational operating
legal procurement audit assurance internal external third party third-party vendor vendors supplier suppliers
policy policies standard standards procedure procedures framework frameworks control controls register
management model models programme program project process processes workflow workflows stage stages trigger
rule rules type types attribute attributes category categories tier template templates assessment assessments
questionnaire questionnaires due diligence review reviews report reports reporting incident incidents issue
issues appetite tolerance capacity limit limits key indicator indicators metric metrics loss event events
annual quarterly monthly daily weekly date dates version draft final live new launch launching created
approved rejected submitted pending active archive archived recycle bin attribute details builder
customer customers client clients employee employees staff people culture talent workforce human resources hr
strategy communications treasury planning payments shared infrastructure cloud network networks resilience
analytics platform platforms digital channels release core banking enterprise integrated integration
directory directories contents content section sections appendix table figure chapter page slide notes
introduction purpose scope overview summary background objectives objective outcomes outcome approach
definitions definition glossary terms term references reference governance oversight accountability
responsible accountable consulted informed matrix matrices structure structures chart org
north south east west central global regional local international domestic united states kingdom
street road avenue lane drive court place square plaza tower building floor suite
high medium low critical elevated moderate zero severe significant major minor rare likely unlikely possible
almost certain biennial effective funding conduct anonymous training induction coaching onboarding offboarding
artificial intelligence generative machine learning federal reserve central authority regulator regulators
dashboard portal system systems application applications tool tools module modules instance environment
staffing consulting consultancy solutions analytics technologies technology labs advisory logistics software
networks media health healthcare insurance securities investments ventures associates industries enterprises
america europe asia india singapore london new york mumbai bangalore warsaw dublin
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december
yes no not none all any other others select add edit delete save cancel submit view search home settings
""".split())

ROLE_WORDS = {"ceo", "cfo", "cio", "cro", "coo", "cpo", "dpo", "ciso", "cto", "vp", "svp", "evp", "gc"}


def fold(text: str) -> str:
    """Lower-case ASCII letters only: 'Brännström' -> 'brannstrom'."""
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower())


def tokens_of(name: str) -> List[str]:
    return [t for t in re.split(r"\s+", name.strip()) if t]


def strip_name(raw: str) -> str:
    """Remove titles, possessive 's, brackets and trailing punctuation."""
    name = re.sub(r"\s+", " ", raw).strip(" ,;:()[]{}\"'“”")
    name = re.sub(r"['’]s$", "", name)
    words = name.split(" ")
    while words and words[0].lower().rstrip(".") in TITLES:
        words = words[1:]
    return " ".join(words)


@dataclass
class Person:
    """An accepted person and the evidence for it."""
    first: str
    middle: List[str]
    last: str
    confidence: float
    evidence: Set[str] = field(default_factory=set)
    forms: Set[str] = field(default_factory=set)   # exact surface strings seen
    firsts: Set[str] = field(default_factory=set)  # every spelling of the first name seen (OCR varies)

    @property
    def key(self) -> str:
        return "person:" + fold(self.first[:1]) + ":" + fold(self.last)


# --------------------------------------------------------------- the detector
class NameDetector:
    """Document-level person-name detection (see module docstring)."""

    # Table header words that announce a column of people.
    HEADER_CUE = re.compile(r"\b(name|names|user|users|owner|owners|contact|contacts|employee|person|people|member|members|"
                            r"approver|approvers|reviewer|reviewers|assignee|author|accountable|responsible|"
                            r"prepared by|approved by|signatory|attendee|attendees|participant|staff)\b", re.I)
    # Phrases directly in front of a name.
    CUE_BEFORE = re.compile(
        r"(?:\b(?:led|owned|approved|reviewed|prepared|signed|authored|chaired|managed|sponsored|requested|raised|"
        r"submitted|escalated|assigned|completed|reported|presented|written|endorsed|nominated|appointed)\s+by|"
        r"\b(?:owner|contact|name|author|attn|attention|dear|hi|hello|regards|sincerely|from|to|cc|assignee|"
        r"approver|reviewer|requester|sponsor|chair|chairperson|delegate|deputy|manager|employee|"
        r"accountable owner|risk owner|control owner|issue owner|action owner)\s*[:,\-–—]?)\s+$",
        re.I)
    # An employee/staff id right after the name: "Naomi K. Osadebe (EMP-41077".
    ID_AFTER = re.compile(r"^\s*[,(–—_-]?\s*\(?\s*(?:(?:EMP|EMPL|MER|CTR|CON|STF|USR|DIR)(?:-|\s?\d)|\[EMPLOYEE_ID_\d)")
    # A role right after the name: "Marguerite Vossberg, Chief Executive Officer"
    ROLE_AFTER = re.compile(r"^\s*[,(–—-]\s*(?:the\s)?(?:chief|head|director|vp|vice|general counsel|manager|"
                            r"officer|ceo|cfo|cio|cro|coo|dpo|ciso)\b", re.I)

    # "Dear Ms Prieto-Ramos", "Mr. Okafor": a title makes a lone surname a person.
    TITLE_SURNAME = re.compile(rf"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?[ \t]+({TOKEN}(?:-{TOKEN})?)(?![\w@])")

    def __init__(self, nlp=None):
        self.nlp = nlp

    # ---------------------------------------------------------- public API
    def detect(self, blocks: List[Tuple[str, str, dict]], emails: List[str]) -> List[dict]:
        """blocks: (block_key, text, info) with info = {picture, table_header, metadata_field}.
        emails: every e-mail address found in the document.
        Returns span dicts: {block, start, end, value, confidence, method, key}."""
        # Not from screenshots/figures: their OCR is full of user names in lower case ("daniela").
        self._lower_words = self._lowercase_vocabulary(
            text for _, text, info in blocks if not info.get("picture") and not info.get("figure"))
        self._email_names = self._names_from_emails(emails)
        self._orgs: Set[str] = set()                      # names seen with a company suffix
        people: Dict[str, Person] = {}

        for cand, conf, method in self._candidates(blocks):
            self._accept(people, cand, conf, method)

        # Line-shaped names corroborated by an e-mail (org charts, directories).
        for _, text, info in blocks:
            for line in text.split("\n"):
                m = LINE_NAME_RE.match(line)
                if m:
                    name = strip_name(m.group(1))
                    if self._email_match(name):
                        self._accept(people, name, 0.9, "email_match")
        found = self._propagate(people, blocks)
        taken = {}
        for f in found:
            taken.setdefault(f["block"], []).append((f["start"], f["end"]))
        found += self._fuzzy_mentions(people, blocks, taken)
        return found + self._title_surnames(blocks, found)

    def _title_surnames(self, blocks, already) -> List[dict]:
        """Surname right after a title ("Ms Prieto-Ramos") when no known person covers it."""
        out = []
        taken = {}
        for f in already:
            taken.setdefault(f["block"], []).append((f["start"], f["end"]))
        for key, text, _info in blocks:
            for m in self.TITLE_SURNAME.finditer(text):
                s, e = m.start(1), m.end(1)
                surname = m.group(1)
                if surname.lower() in STOP or surname.lower() in self._lower_words \
                        or any(s < te and ts < e for ts, te in taken.get(key, [])):
                    continue
                out.append({"block": key, "start": s, "end": e, "value": surname, "confidence": 0.85,
                            "method": "title_surname", "key": "person:title:" + fold(surname)})
        return out

    # ------------------------------------------------------ discovery
    def _candidates(self, blocks):
        texts_for_ner = []
        for key, text, info in blocks:
            if info.get("metadata_field") in ("author", "last_modified_by"):
                name = strip_name(re.sub(r"^\s*\[[^\]]*\]\s*", "", text))      # "[XY] Jane Example"
                if NAME_RE.fullmatch(name):
                    yield name, 0.9, "document_property"
                continue
            # Context cues anywhere in the text.
            for m in NAME_RE.finditer(text):
                name = strip_name(m.group(0))
                before = text[max(0, m.start() - 40):m.start()]
                after = text[m.end():m.end() + 30]
                if self.ORG_SUFFIX.match(after):
                    self._orgs.add(fold(name))
                    continue                                   # "Meridian Staffing Ltd" is a company
                if self.ID_AFTER.match(after):
                    yield name, 0.95, "context_id"
                elif self.CUE_BEFORE.search(before):
                    yield name, 0.85, "context_cue"
                elif self.ROLE_AFTER.match(after):
                    yield name, 0.8, "context_role"
                else:
                    # "Amanda Singh": a known given name followed by a capitalised surname
                    toks = tokens_of(self._trim(name))
                    if 2 <= len(toks) <= 4 and fold(toks[0]) in GIVEN_NAMES and len(fold(toks[-1])) >= 2:
                        yield " ".join(toks), 0.75, "given_name"
            # Name columns of tables: every line of the cell that is shaped like a name.
            if info.get("table_header") and self.HEADER_CUE.search(info["table_header"]):
                for line in re.split(r"\n|[,;/]| and | & ", text):
                    m = LINE_NAME_RE.match(line)
                    if m:
                        yield strip_name(m.group(1)), 0.85, "table_column"
            if not info.get("picture"):
                texts_for_ner.append(text)
        yield from self._ner_candidates(texts_for_ner)

    def _ner_candidates(self, texts):
        if self.nlp is None or not texts:
            return
        # Newlines separate cells/lines; spaCy should not join names across them.
        docs = self.nlp.pipe((t.replace("\n", " \n ") for t in texts), batch_size=64)
        for doc in docs:
            for ent in doc.ents:
                if ent.label_ != "PERSON":
                    continue
                for part in ent.text.split("\n"):
                    m = NAME_RE.search(part)
                    if m:
                        yield strip_name(m.group(0)), 0.6, "ner"

    # ----------------------------------------------------- validation
    @staticmethod
    def _lowercase_vocabulary(texts) -> Set[str]:
        """Words that appear in lower case somewhere in the document = common words."""
        vocab = set()
        for text in texts:
            vocab.update(w for w in re.findall(rf"(?<![\w.@-])[{LO}]{{3,}}(?![\w@])", text))
        return vocab

    @staticmethod
    def _names_from_emails(emails) -> List[Tuple[str, str]]:
        """(first initial or first name, surname) pairs from local parts like n.osadebe / naomi.osadebe."""
        pairs = []
        for e in emails:
            local = e.split("@")[0].lower().strip("._-")
            m = re.fullmatch(r"([a-z]+)[._-]([a-z]+)(?:[._-]?\d+)?", local)
            if m:
                pairs.append((m.group(1), m.group(2)))
        return pairs

    def _email_match(self, name: str) -> bool:
        toks = tokens_of(name)
        if len(toks) < 2:
            return False
        first, last = fold(toks[0]), fold(toks[-1])
        if not first or len(last) < 2:
            return False
        for f, s in self._email_names:
            if last == s or (len(s) >= 5 and last.startswith(s)) or s == fold("".join(toks[-2:])):
                if first.startswith(f) or (len(f) == 1 and first[:1] == f):
                    return True
        return False

    def _plausible(self, name: str, method: str) -> bool:
        if fold(name) in getattr(self, "_orgs", set()):
            return False
        toks = tokens_of(name)
        if len(toks) < 2 or len(toks) > 5:
            return False
        last = toks[-1]
        if re.fullmatch(INITIAL, last) or len(fold(last)) < 2:
            return False
        for i, t in enumerate(toks):
            if re.fullmatch(INITIAL, t):
                continue                                      # "A." is an initial, not the word "a"
            low = t.lower().rstrip(".")
            if low in STOP or low in ROLE_WORDS:
                return False
            if re.fullmatch(r"[A-Z]{2,}", t) and not (i == 0 and len(t) == 2):
                return False                                  # CHIEF, CEO (but JT Harrow is fine)
        # A word used in lower case elsewhere in this document is a common word, not a name -
        # unless an e-mail address independently confirms the person.
        words = [t for t in toks if not re.fullmatch(INITIAL, t) and not re.fullmatch(PAIR_INITIALS, t)]
        common = [t for t in words if t.lower() in self._lower_words]
        if common and method not in ("email_match", "document_property", "context_id"):
            if len(common) == len(words) or not self._email_match(name):
                return False
        return True

    def _is_common(self, token: str) -> bool:
        if re.fullmatch(INITIAL, token):
            return False
        low = token.lower().rstrip(".")
        return low in STOP or low in ROLE_WORDS or low in self._lower_words \
            or bool(re.fullmatch(r"[A-Z]{3,}", token))

    def _trim(self, name: str) -> str:
        """Cut words that OCR'd table columns (or long title-case runs) glue onto a name.

        "High Yusuf O. Balogun"            -> "Yusuf O. Balogun"   (leading common word)
        "Environmental Risk Policy Yevgeni A. Sorokina" -> "Yevgeni A. Sorokina"
        "N. K. Delphine R. Okonjo"         -> "Delphine R. Okonjo" (a neighbour's initials)
        "Raghavan M. T. Achebe"            -> "M. T. Achebe"       (a neighbour's surname)
        "Tobias Lindqvist Coaching"        -> "Tobias Lindqvist"   (text after a known surname)
        """
        surnames = {s for _, s in self._email_names}
        toks = tokens_of(name)
        while True:
            before = list(toks)
            while len(toks) > 2 and not re.fullmatch(INITIAL, toks[0]) and self._is_common(toks[0]):
                toks = toks[1:]
            while len(toks) > 2 and self._is_common(toks[-1]):
                toks = toks[:-1]
            # Leading initials followed by a full first name belong to someone else.
            if len(toks) > 2 and re.fullmatch(INITIAL, toks[0]):
                for j in range(1, len(toks) - 1):
                    if not re.fullmatch(INITIAL, toks[j]):
                        toks = toks[j:]
                        break
            # Anything after a surname confirmed by an e-mail address is another name or noise.
            for j in range(1, len(toks) - 1):
                if fold(toks[j]) in surnames and self._email_match(" ".join(toks[:j + 1])):
                    toks = toks[:j + 1]
                    break
            # A leading word that is another person's confirmed surname belongs to that person.
            if len(toks) > 2 and self._is_known_surname(toks[0], surnames) and fold(toks[-1]) != fold(toks[0]):
                toks = toks[1:]
            if toks == before:
                break
        # Very long runs: a person's name is at most first + 2 middles + last.
        if len(toks) > 4:
            toks = toks[-4:]
        return " ".join(toks)

    @staticmethod
    def _is_known_surname(token: str, surnames: Set[str]) -> bool:
        """'Marchetti-Lang' counts as the known surname 'marchetti' (from s.marchetti@...)."""
        f = fold(token)
        return f in surnames or any(len(s) >= 5 and f.startswith(s) for s in surnames)

    # Legal-entity suffix right after the name (no comma: "Naomi Osadebe, Group CRO" is a person).
    ORG_SUFFIX = re.compile(r"^[ \t]+(?:Ltd|Limited|Inc|LLC|LLP|PLC|Plc|Corp|Corporation|GmbH|AG|SA|S\.A\.|BV|NV|"
                            r"Pvt|Pte|Co\.|Holdings)\b\.?")

    def _accept(self, people: Dict[str, Person], name: str, conf: float, method: str):
        name = self._trim(strip_name(name))
        if method == "ner" and len(fold(tokens_of(name)[-1] if name else "")) < 3:
            return                                         # "Generative Al" - NER alone is not enough
        if not self._plausible(name, method):
            return
        evidence = {method}
        if method != "email_match" and self._email_match(name):
            conf = max(conf, 0.9)
            evidence.add("email_match")
        toks = tokens_of(name)
        first, last = toks[0], toks[-1]
        middle = toks[1:-1]
        person = Person(first, middle, last, conf, evidence, {name}, {first})
        existing = people.get(person.key)
        if existing is None:
            people[person.key] = person
            return
        existing.confidence = max(existing.confidence, conf)
        existing.evidence |= evidence
        existing.forms.add(name)
        existing.firsts.add(first)
        # Prefer the most complete spelling of the first name ("Naomi" over "N.") for display.
        if len(fold(first)) > len(fold(existing.first)):
            existing.first = first
        if middle and not existing.middle:
            existing.middle = middle

    # ----------------------------------------------------- propagation
    def _surface_patterns(self, p: Person) -> List[Tuple[re.Pattern, float]]:
        """Regexes for every way the document may write this person, most specific first."""

        def word(w):  # tolerate OCR line-breaks inside hyphenated names
            return r"-\s*".join(re.escape(x) for x in w.split("-"))

        last = word(p.last)
        full_firsts = sorted({f for f in p.firsts | {p.first} if not re.fullmatch(INITIAL, f)}, key=len, reverse=True)
        first = "(?:" + "|".join(word(f) for f in full_firsts) + ")" if full_firsts else None
        init = re.escape(p.first[0])
        # middle initials or one middle name, on the same line; one line break allowed before the surname
        mids = r"(?:[ \t]*(?:[A-Z]\.(?:[ \t]?-?[A-Z]\.)?|[ \t][A-Z][a-z]+)){0,2}"
        gap = r"(?:[ \t]+|[ \t]*\n[ \t]*)"
        pats = [
            # F. [M.] Last  /  F.-E. Last  /  F.M. Last
            (rf"(?<![\w@.]){init}\.(?:[ \t]?-?[A-Z]\.)*{mids}{gap}?{last}(?![\w@])", 0.95),
            # FM Last / F Last
            (rf"(?<![\w@.]){init}[A-Z]?[ \t]{last}(?![\w@])", 0.85),
        ]
        if first:
            pats = [
                # First [Middle(s)] Last
                (rf"(?<![\w@.]){first}{mids}{gap}{last}(?![\w@])", 1.0),
                # Last, First
                (rf"(?<![\w@.]){last},[ \t]{first}(?![\w@])", 0.95),
            ] + pats
        out = [(re.compile(rx, re.I if len(fold(p.last)) >= 4 else 0), w) for rx, w in pats]
        # Bare first name ("Rafael's own record"): distinctive first names of confirmed people only.
        if p.confidence >= 0.85:
            for f in full_firsts:
                if self._distinctive(f) and "-" not in f:
                    out.append((re.compile(rf"(?<![\w@.-]){word(f)}(?:['’]s)?(?![\w@-])"), 0.7))
        # Bare surname: only when it is distinctive and not an ordinary word in this document.
        if self._distinctive(p.last):
            # not inside a hyphenated surname ("Okonkwo-Bell"), but "¥-Sorokina" (OCR noise) counts
            out.append((re.compile(rf"(?<![\w@.])(?<![^\W\d_]-){last}(?:['’]s)?(?![\w@-])"), 0.75))
        return out

    @staticmethod
    def _edit_distance(a: str, b: str, limit: int = 2) -> int:
        """Levenshtein distance, stopping early above limit."""
        if abs(len(a) - len(b)) > limit:
            return limit + 1
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            if min(cur) > limit:
                return limit + 1
            prev = cur
        return prev[-1]

    # Initials or a first name, then a capitalised word: candidate for an OCR-damaged surname.
    FUZZY_RE = re.compile(rf"(?<![\w@.])((?:[{UP}]\.?[ \t]?-?){{1,3}}|{TOKEN}[ \t]+(?:[{UP}]\.?[ \t]+)?)({TOKEN})(?![\w@])")

    def _fuzzy_mentions(self, people, blocks, taken_by_block) -> List[dict]:
        """'N. K Osadehe' (OCR for Osadebe): initials/first name of a known person followed by a
        word one edit (two for long names) away from that person's surname."""
        by_initial = {}
        for p in people.values():
            if len(fold(p.last)) >= 6:
                by_initial.setdefault(fold(p.first[:1]), []).append(p)
        out = []
        for key, text, _info in blocks:
            for m in self.FUZZY_RE.finditer(text):
                lead, word = m.group(1), m.group(2)
                s, e = m.start(), m.end()
                if any(s < te and ts < e for ts, te in taken_by_block.get(key, [])):
                    continue
                w = fold(word)
                for p in by_initial.get(fold(lead[:1]), []):
                    if w == fold(p.last):
                        continue                                # exact forms are handled already
                    limit = 1 if len(fold(p.last)) < 9 else 2
                    if self._edit_distance(w, fold(p.last), limit) <= limit:
                        lead_word = fold(lead.split()[0]) if lead.strip() and not lead.strip().endswith(".") else ""
                        if lead_word and len(lead_word) > 1 and lead_word not in {fold(f) for f in p.firsts | {p.first}}:
                            continue                            # different first name
                        out.append({"block": key, "start": s, "end": e, "value": m.group(0),
                                    "confidence": round(p.confidence * 0.85, 2), "method": "ocr_fuzzy", "key": p.key})
                        taken_by_block.setdefault(key, []).append((s, e))
                        break
        return out

    def _distinctive(self, surname: str) -> bool:
        f = fold(surname)
        return len(f) >= 6 and surname.lower() not in self._lower_words and surname.lower() not in STOP

    def _propagate(self, people: Dict[str, Person], blocks) -> List[dict]:
        found = []
        compiled = [(p, self._surface_patterns(p)) for p in people.values()]
        for key, text, info in blocks:
            taken: List[Tuple[int, int]] = []
            spans = []
            for p, patterns in compiled:
                for rx, weight in patterns:
                    for m in rx.finditer(text):
                        s, e = m.start(), m.end()
                        value = re.sub(r"['’]s$", "", m.group(0))
                        e = s + len(value)
                        spans.append((s, e, value, p, weight))
            # Longest match wins where forms overlap ("Naomi K. Osadebe" over "Osadebe").
            for s, e, value, p, weight in sorted(spans, key=lambda x: (-(x[1] - x[0]), x[0])):
                if any(s < te and ts < e for ts, te in taken):
                    continue
                taken.append((s, e))
                found.append({"block": key, "start": s, "end": e, "value": value,
                              "confidence": round(min(0.99, p.confidence * weight + (0.05 if weight == 1.0 else 0)), 2),
                              "method": "+".join(sorted(p.evidence)), "key": p.key})
        return found
