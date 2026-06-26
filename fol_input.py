"""
Input-side support for Prover9 (LADR) and CLIF (Common Logic) syntax in the FOL
expression tester.

The tester validates expressions with NLTK's LogicParser, which speaks an infix
syntax: `all x.(P(x) -> Q(x))`, `exists x.P(x)`, with `&`, `|`, `->`, `<->`, `-`.
Users who think in BFO/CLIF or who paste Prover9 output should not have to
re-type. This module detects those two syntaxes and converts them to the internal
infix form so the existing term-extraction and BFO checks apply unchanged.

Scope: the common first-order subset (quantifiers, the boolean connectives, and
n-ary predicates). Sort declarations, functions, and CLIF's sequence markers /
`cl-text` wrappers are tolerated but not deeply modeled; conversion is best-effort
and reports a note when it falls back.
"""
import re


def detect_syntax(expr):
    """Return 'clif' | 'prover9' | 'instance_of' | 'traditional' | None.

    Detection is ordered so the more distinctive syntaxes win: CLIF is fully
    parenthesized prefix; Prover9 uses `all X`/`exists X` with a leading-cap
    variable and `&`/`->`. instance_of and traditional match the existing tester
    formats.
    """
    s = expr.strip()
    if not s:
        return None
    # CLIF: prefix s-expressions. A leading '(' plus a CL keyword.
    if s.startswith("(") and re.search(r"\((forall|exists|and|or|not|if|iff)\b",
                                       s, re.IGNORECASE):
        return "clif"
    if re.search(r"\(\s*(instance[_-]of|cl-text|cl:text)\b", s, re.IGNORECASE) \
            and s.startswith("("):
        return "clif"
    # Prover9: `all X ...` / `exists X ...` with an upper-case variable, or the
    # `&` conjunction / `->` arrow that the internal syntax also uses but which,
    # combined with a `all X` (no dot), signals LADR.
    if re.search(r"\b(all|exists)\s+[A-Z]\w*", s) and "." not in s.split("(")[0]:
        return "prover9"
    if re.search(r"\bend_of_list\b|\bformulas\s*\(", s):
        return "prover9"
    # Existing tester formats.
    if "instance_of" in s:
        return "instance_of"
    if re.search(r"\b(Continuant|Occurrent|Process|Object|Quality|Entity)\s*\(",
                 s):
        return "traditional"
    return None


# -- Prover9 -> internal -----------------------------------------------------

def prover9_to_internal(expr):
    """Convert a single Prover9 formula to NLTK infix syntax.

    Handles the assumptions/goals list wrappers, strips the trailing clause dot,
    and rewrites `all X all T (...)` quantifier runs into `all X.all T.(...)`.
    Connectives (&, |, ->, <->, -) already match NLTK and pass through.
    """
    s = expr.strip()
    # Drop Prover9 file scaffolding if present, keep the formula bodies.
    s = re.sub(r"set\([^)]*\)\s*\.", " ", s)
    s = re.sub(r"formulas\([^)]*\)\s*\.", " ", s)
    s = s.replace("end_of_list.", " ")
    # Comments.
    s = re.sub(r"%[^\n]*", " ", s)
    s = s.strip()
    # A single formula ends with '.'; drop one trailing dot if present.
    if s.endswith("."):
        s = s[:-1]
    # Insert a dot after each quantifier+variable so NLTK reads it as a binder:
    #   "all X all T (" -> "all X.all T.("
    s = re.sub(r"\b(all|exists)\s+([A-Za-z]\w*)\s+", r"\1 \2.", s)
    s = re.sub(r"\b(all|exists)\s+([A-Za-z]\w*)\s*\(", r"\1 \2.(", s)
    return re.sub(r"\s+", " ", s).strip()


# -- CLIF -> internal --------------------------------------------------------

class _SExprParser:
    """Minimal s-expression reader for the CLIF first-order subset."""

    def __init__(self, text):
        self.toks = self._tokenize(text)
        self.i = 0

    @staticmethod
    def _tokenize(text):
        # Strip CLIF line comments (;; ...) and the cl-text/cl:text wrapper name
        # is handled structurally below.
        text = re.sub(r";;[^\n]*", " ", text)
        return re.findall(r"\(|\)|[^()\s]+", text)

    def parse(self):
        forms = []
        while self.i < len(self.toks):
            forms.append(self._read())
        return forms

    def _read(self):
        tok = self.toks[self.i]
        self.i += 1
        if tok == "(":
            lst = []
            while self.i < len(self.toks) and self.toks[self.i] != ")":
                lst.append(self._read())
            self.i += 1  # consume ')'
            return lst
        return tok


_CONNECTIVE = {"and": "&", "or": "|"}


def _sexpr_to_internal(node):
    """Render a parsed CLIF s-expression node as NLTK infix syntax."""
    if isinstance(node, str):
        return node
    if not node:
        return ""
    head = node[0]
    if isinstance(head, list):
        # A bare list of forms (e.g. a cl-text body): conjoin them.
        rendered = [_sexpr_to_internal(n) for n in node]
        rendered = [r for r in rendered if r]
        return " & ".join(f"({r})" for r in rendered)
    h = head.lower()

    if h in ("cl-text", "cl:text", "cl-module", "cl:module"):
        # (cl-text NAME form...) -> conjoin the forms, skip the name token.
        body = [n for n in node[1:] if not isinstance(n, str)]
        rendered = [_sexpr_to_internal(n) for n in body]
        rendered = [r for r in rendered if r]
        return " & ".join(f"({r})" for r in rendered)

    if h in ("forall", "exists"):
        quant = "all" if h == "forall" else "exists"
        varspec = node[1]
        vars_ = varspec if isinstance(varspec, list) else [varspec]
        # Variables may be (x) or (x t) or typed (x Type) -- take the names.
        names = [v if isinstance(v, str) else v[0] for v in vars_]
        body = _sexpr_to_internal(node[2]) if len(node) > 2 else ""
        prefix = "".join(f"{quant} {n}." for n in names)
        return f"{prefix}({body})"

    if h == "not":
        return f"-({_sexpr_to_internal(node[1])})"

    if h in _CONNECTIVE:
        op = _CONNECTIVE[h]
        parts = [f"({_sexpr_to_internal(n)})" for n in node[1:]]
        return f" {op} ".join(parts)

    if h == "if":
        return f"({_sexpr_to_internal(node[1])}) -> ({_sexpr_to_internal(node[2])})"

    if h == "iff":
        return f"({_sexpr_to_internal(node[1])}) <-> ({_sexpr_to_internal(node[2])})"

    if h == "=":
        return f"({_sexpr_to_internal(node[1])} = {_sexpr_to_internal(node[2])})"

    # Atomic predicate: (pred a b c) -> pred(a,b,c)
    args = ",".join(_sexpr_to_internal(n) for n in node[1:])
    return f"{head}({args})"


def clif_to_internal(expr):
    """Convert a CLIF expression to NLTK infix syntax (best effort)."""
    forms = _SExprParser(expr).parse()
    rendered = [_sexpr_to_internal(f) for f in forms]
    rendered = [r for r in rendered if r]
    if len(rendered) == 1:
        return rendered[0]
    return " & ".join(f"({r})" for r in rendered)


# -- public entry point ------------------------------------------------------

def prepare_expression(raw):
    """Normalize raw user input to internal infix syntax for the tester.

    Returns (internal_expr, detected_format, note):
      - internal_expr: the converted expression (or the original when no
        conversion applies).
      - detected_format: 'clif' | 'prover9' | 'instance_of' | 'traditional' | None.
      - note: a short human-readable note when a conversion was performed or
        failed, else None.
    """
    syntax = detect_syntax(raw)
    note = None
    internal = raw
    try:
        if syntax == "prover9":
            internal = prover9_to_internal(raw)
            note = "Interpreted as Prover9 syntax and converted for validation."
        elif syntax == "clif":
            internal = clif_to_internal(raw)
            note = "Interpreted as CLIF syntax and converted for validation."
    except Exception as e:  # noqa: BLE001
        note = f"Could not fully convert {syntax} input ({e}); validating as-is."
        internal = raw
    return internal, syntax, note
