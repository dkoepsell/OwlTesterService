"""
String-aware lexer and reader for ISO/IEC 24707 Common Logic Interchange Format.

The original FOL tester shipped a bare s-expression reader (fol_input._SExprParser)
that split on whitespace and parentheses only. That is fine for the small,
comment-free expressions a user types into the tester, but it is not sufficient
for the vendored BFO-2020 theory (bfo/bfo-2020.clif), which is dense with
single-quoted cl:comment prose and double-quoted cl:ttl URLs. Splitting that prose
on whitespace leaks dozens of spurious "predicate" atoms (ISO/IEC, cl:, both, at,
...) into any axiom extraction.

This module reads CLIF the way the standard defines it:

  - bare names                  ->  str
  - 'single-quoted enclosed'    ->  CLString  (CL "enclosed name")
  - "double-quoted strings"     ->  CLString  (CL "quoted string")
  - a backslash escape (\\' \\" \\\\)  ->  the following char, literally
  - ;; line comments            ->  stripped

A CLString is a str subclass, so existing walkers that treat atoms as plain
strings keep working; code that needs to tell comment/title prose apart from real
names checks isinstance(tok, CLString) and skips it.
"""


class CLString(str):
    """A CLIF quoted literal (single- or double-quoted enclosed/quoted name).

    Subclasses str so s-expression walkers can keep treating atoms as strings,
    while isinstance(node, CLString) distinguishes literal prose (comments, URLs)
    from genuine symbols and so keeps it out of the axiom signature.
    """
    __slots__ = ()


_WHITESPACE = " \t\r\n\f"
_DELIMITERS = "()'\"" + _WHITESPACE


def tokenize(text):
    """Return a flat list of CLIF tokens.

    Tokens are the literal strings '(' and ')', CLString instances for quoted
    literals, and plain str for bare names. ;; line comments are dropped.
    """
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _WHITESPACE:
            i += 1
            continue
        if c == ";" and i + 1 < n and text[i + 1] == ";":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if c in "()":
            tokens.append(c)
            i += 1
            continue
        if c in "'\"":
            quote = c
            i += 1
            buf = []
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    # Backslash escape (CL 24707): the next char is literal.
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1  # closing quote
                    break
                buf.append(text[i])
                i += 1
            tokens.append(CLString("".join(buf)))
            continue
        # Bare name: run up to the next delimiter.
        j = i
        while j < n and text[j] not in _DELIMITERS:
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def parse(text):
    """Parse CLIF text into a list of top-level s-expressions.

    Lists are Python lists; bare names are str; quoted literals are CLString.
    Unbalanced parentheses raise ValueError.
    """
    toks = tokenize(text)
    pos = 0
    length = len(toks)

    def read():
        nonlocal pos
        tok = toks[pos]
        pos += 1
        if tok == "(":
            lst = []
            while pos < length and toks[pos] != ")":
                lst.append(read())
            if pos >= length:
                raise ValueError("CLIF parse error: unbalanced '('")
            pos += 1  # consume ')'
            return lst
        if tok == ")":
            raise ValueError("CLIF parse error: unexpected ')'")
        return tok

    forms = []
    while pos < length:
        forms.append(read())
    return forms
