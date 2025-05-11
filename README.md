# FOL-BFO-OWL Tester

## 🧠 Introduction

**FOL-BFO-OWL Tester** is a comprehensive web service for validating and analyzing First-Order Logic (FOL) expressions and OWL ontologies using the **Basic Formal Ontology (BFO)** framework.

Designed for **ontology developers, researchers, and students**, this tool ensures that your logical expressions and ontological structures conform to BFO standards, revealing structural and semantic issues and offering real-world implications of your ontologies.

---

## ⚙️ How It Works

### 🔍 FOL Expression Testing

1. **Enter a FOL Expression**: Input your expression in the provided field.
2. **Test the Expression**: Click `Test Expression` to analyze it.
3. **Review Results**: The system will validate syntax, check for BFO compatibility, and highlight issues.
4. **Fix and Refine**: Use the feedback to adjust and correct expressions.

### 🧩 Ontology Analysis

1. **Upload OWL File**: Load your ontology into the system.
2. **Review Structure**: View analysis of class hierarchies, axioms, and logical relations.
3. **Explore FOL Premises**: Extract and inspect FOL expressions derived from your ontology.
4. **Generate Implications**: Use AI to infer real-world consequences based on your ontology's logic.

### ✅ The system checks for:
- FOL syntax correctness
- BFO class and relation recognition
- Use of non-BFO terms
- Structural errors in logic
- Ontology consistency and contradictions
- Class hierarchies and relationships
- Axiom validity and coverage
- Logical entailments and real-world implications

---

## 🧱 About BFO

The **Basic Formal Ontology (BFO)** is a domain-neutral top-level ontology used to support data integration and interoperability across disciplines.

BFO distinguishes between:
- **Continuants**: Persistent entities (e.g., objects, qualities, functions)
- **Occurrents**: Temporal entities (e.g., events, processes)

🔗 [Learn more about BFO](https://basic-formal-ontology.org)

---

## 🔎 Ontology Analysis Features

- **Upload and Analyze OWL Files**
  - Class hierarchies
  - Relationship maps
  - Axiom extraction
  - Consistency checks with reasoners
  - Statistical structure summaries

- **FOL Premises Extraction**
  - OWL → FOL translation
  - Human-readable logic summaries
  - Pattern and rule identification

- **Real-World Implications Generation**
  - AI-generated scenarios based on ontology logic
  - Concrete use-cases with explanations
  - Domain-specific insight generation

- **History and Tracking**
  - View previously uploaded ontologies
  - Compare different versions
  - Build a knowledge base over time

---

## 🔄 Recent Updates

✅ **May 11, 2025**
- Added default BFO terms when no ontology file is available
- Fixed parser initialization bugs
- Improved term extraction in BFO-style logic
- Enhanced support for traditional and BFO notation
- Expanded ontology analysis capabilities

---

## ✍️ FOL Syntax Guide

| **Logic** | **Symbol** | **Example** |
|-----------|------------|-------------|
| Universal Quantifier | `forall` | `forall x (Human(x) -> Mortal(x))` |
| Existential Quantifier | `exists` | `exists x (Student(x) & Happy(x))` |
| AND (Conjunction) | `&` | `Tall(John) & Strong(John)` |
| OR (Disjunction) | `\|` | `Happy(Mary) \| Sad(Mary)` |
| NOT (Negation) | `~` | `~Raining(today)` |
| Implication | `->` | `Wet(Grass) -> Rained(Recently)` |
| Biconditional | `<->` | `Bachelor(x) <-> (Man(x) & ~Married(x))` |

> 💡 *Use lowercase for variables, uppercase for predicates/constants.*

---

## 🔤 FOL Notation Formats

### ✅ Traditional Notation (Simpler)
```text
forall x (Human(x) -> Mammal(x))
```

### ✅ BFO Standard Notation (Recommended)
```text
forall x, t (instance_of(x, Human, t) -> instance_of(x, Mammal, t))
```
- Uses `instance_of` and time-indexed class membership.
- Supports temporal reasoning in line with BFO structure.

> The system **auto-detects** the format and provides context-sensitive feedback.

---

## 🛠️ Project Information

Originally developed by [@dkoepsell](https://github.com/dkoepsell), the FOL-BFO-OWL Tester is built for deep semantic analysis of logical and ontological structures.

### 🔧 Tech Stack
- **Backend**: Python, Flask, NLTK, Owlready2, PostgreSQL
- **Frontend**: HTML5, Bootstrap 5, JavaScript
- **AI Integration**: OpenAI API (for implication generation)
- **Ontology Reasoners**: HermiT, Pellet

---

## 🏷️ Tags

`#FormalOntology` `#OntologyEngineering` `#BasicFormalOntology` `#FirstOrderLogic` `#SemanticWeb` `#AIReasoning` `#OWL` `#BFO`
