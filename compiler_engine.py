import os
import re
from typing import List, Set, NamedTuple, Dict, Any

class Token(NamedTuple):
    type: str
    value: str
    line: int
    column: int

class ResumeLexer:
    def __init__(self, text: str):
        self.text = text
        self.line = 1
        self.column = 1
        
        self.token_specs = [
            ('SECTION_HEADER', r'\b(education|experience|employment|projects|skills|summary|work history|certifications|awards|about me)\b'),
            ('SKILL_AI', r'\b(machine learning|xai|explainable ai|computer vision|deep learning|neural networks?|siamese networks?|attention modules?|nlp|natural language processing|llms?|large language models?|rag|retrieval augmented generation|reinforcement learning|scikit-learn)\b'),
            ('SKILL_LANG', r'\b(python|java|javascript|c\+\+|c#|c|micropython|typescript|go|golang|rust|sql|html|css|php|ruby|scala|kotlin|swift)\b'),
            ('SKILL_TOOL', r'\b(docker|kubernetes|k8s|git|github|aws|amazon web services|azure|gcp|google cloud|esp32|mobilenet|react|react\.js|reactjs|vue|vue\.js|angular|node\.js|nodejs|flask|django|pytorch|tensorflow|keras|chromadb|mongodb|postgresql|mysql|sqlite|redis|jenkins|ansible|terraform)\b'),
            ('SKILL_CONCEPT', r'\b(system design|agile|scrum|ci/cd|continuous integration|algorithmic fairness|one-shot learning|data structures|algorithms|object-oriented programming|oop|microservices|rest api|graphql|cryptography|blockchain)\b'),
            ('EMAIL', r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
            ('PHONE', r'\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}'),
            ('NEWLINE', r'\n'),
            ('WHITESPACE', r'[ \t\r]+'),
            ('NUMBER', r'\b\d+(\.\d+)?\b'),
            ('BULLET', r'^[-*•]\s*'),
            ('WORD', r'\b[a-zA-Z_][a-zA-Z0-9_-]*\b'),
            ('MISMATCH', r'.'),
        ]
        self.regex = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in self.token_specs)

    def tokenize(self) -> List[Token]:
        tokens = []
        for match in re.finditer(self.regex, self.text, re.MULTILINE | re.IGNORECASE):
            kind = match.lastgroup
            value = match.group()
            
            if kind == 'NEWLINE':
                self.line += 1
                self.column = 1
                continue
            elif kind == 'WHITESPACE':
                self.column += len(value)
                continue
            
            tokens.append(Token(kind, value, self.line, self.column))
            self.column += len(value)
        return tokens

class ASTNode:
    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError

class ResumeNode(ASTNode):
    def __init__(self, sections: List['SectionNode'], email: str = "", phone: str = ""):
        self.sections = sections
        self.email = email
        self.phone = phone

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "Resume",
            "email": self.email,
            "phone": self.phone,
            "sections": [s.to_dict() for s in self.sections]
        }

class SectionNode(ASTNode):
    def __init__(self, name: str, items: List[str], skills: List[Token]):
        self.name = name.upper()
        self.items = items
        self.skills = skills

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "Section",
            "name": self.name,
            "items": self.items,
            "skills": [{"type": tok.type, "value": tok.value} for tok in self.skills]
        }

class ResumeParser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token('EOF', '', -1, -1)

    def consume(self, expected_type: str = None) -> Token:
        tok = self.peek()
        self.pos += 1
        return tok

    def is_eof(self) -> bool:
        return self.pos >= len(self.tokens)

    def parse(self) -> ResumeNode:
        sections = []
        email = ""
        phone = ""
        
        current_section_name = "SUMMARY"
        current_items = []
        current_skills = []
        
        while not self.is_eof():
            tok = self.peek()
            
            if tok.type == 'EMAIL' and not email:
                email = self.consume().value
                continue
            elif tok.type == 'PHONE' and not phone:
                phone = self.consume().value
                continue
            
            if tok.type == 'SECTION_HEADER':
                if current_items or current_skills:
                    sections.append(SectionNode(current_section_name, current_items, current_skills))
                
                current_section_name = self.consume().value
                current_items = []
                current_skills = []
                continue
            
            if tok.type in ('SKILL_AI', 'SKILL_LANG', 'SKILL_TOOL', 'SKILL_CONCEPT'):
                current_skills.append(tok)
                self.consume()
            elif tok.type in ('WORD', 'NUMBER', 'BULLET'):
                val = self.consume().value
                if current_items and not current_items[-1].endswith((" ", "\n")):
                    current_items[-1] += " " + val
                else:
                    current_items.append(val)
            else:
                self.consume()
                
        if current_items or current_skills:
            sections.append(SectionNode(current_section_name, current_items, current_skills))
            
        return ResumeNode(sections, email, phone)

class SemanticAnalyzer:
    PREREQUISITES = {
        "react": "javascript",
        "react.js": "javascript",
        "reactjs": "javascript",
        "vue": "javascript",
        "vue.js": "javascript",
        "angular": "javascript",
        "node.js": "javascript",
        "nodejs": "javascript",
        "typescript": "javascript",
        "pytorch": "python",
        "tensorflow": "python",
        "keras": "python",
        "flask": "python",
        "django": "python",
        "scikit-learn": "python",
        "fastapi": "python",
        "micropython": "python"
    }

    def __init__(self, ast: ResumeNode):
        self.ast = ast
        self.symbol_table: Set[str] = set()
        self.semantic_warnings: List[str] = []

    def analyze(self) -> Dict[str, Any]:
        for section in self.ast.sections:
            for skill in section.skills:
                self.symbol_table.add(skill.value.lower())

        auto_injected = []
        for skill in list(self.symbol_table):
            if skill in self.PREREQUISITES:
                prereq = self.PREREQUISITES[skill]
                if prereq not in self.symbol_table:
                    self.semantic_warnings.append(
                        f"Semantic Check: Found '{skill.title()}' but missing base language prerequisite '{prereq.title()}'. Injected."
                    )
                    self.symbol_table.add(prereq)
                    auto_injected.append(prereq)

        return {
            "symbol_table": list(self.symbol_table),
            "warnings": self.semantic_warnings,
            "auto_injected": auto_injected
        }

class IrOptimizer:
    SYNONYM_FOLDING = {
        "reactjs": "React",
        "react.js": "React",
        "react": "React",
        "vue.js": "Vue",
        "vue": "Vue",
        "nodejs": "Node.js",
        "node.js": "Node.js",
        "golang": "Go",
        "go": "Go",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "c++": "C++",
        "c#": "C#",
        "python": "Python",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "machine learning": "Machine Learning",
        "natural language processing": "NLP",
        "nlp": "NLP",
        "large language models": "LLMs",
        "llm": "LLMs",
        "retrieval augmented generation": "RAG",
        "rag": "RAG",
        "docker": "Docker",
        "kubernetes": "Kubernetes",
        "k8s": "Kubernetes",
        "sql": "SQL",
        "system design": "System Design",
        "ci/cd": "CI/CD",
        "continuous integration": "CI/CD"
    }

    def __init__(self, raw_symbol_table: List[str]):
        self.raw_symbol_table = raw_symbol_table

    def optimize(self) -> List[str]:
        optimized_skills = set()
        for skill in self.raw_symbol_table:
            skill_lower = skill.lower()
            if skill_lower in self.SYNONYM_FOLDING:
                optimized_skills.add(self.SYNONYM_FOLDING[skill_lower])
            else:
                optimized_skills.add(skill.title())
        return sorted(list(optimized_skills))

class TargetCodeGenerator:
    @staticmethod
    def generate_rag_query(role: str, company: str, skills: List[str]) -> str:
        skills_str = ", ".join(skills)
        return f"{role} at {company} interview questions. Core skills: {skills_str}."

    @staticmethod
    def generate_evaluator_prompt(role: str, company: str, question: str, answer: str) -> str:
        return f"""You are a highly strict and objective Senior {role} interviewer at {company}.
Evaluate the candidate's technical response to this question:
"{question}"

Candidate's Answer:
"{answer}"

CRITICAL INTERVIEWING INSTRUCTIONS:
1. **ELIMINATE LENGTH BIAS**: Do NOT reward long, verbose, or rambling answers with a high score. A short, technically dense and precise answer (1-2 sentences) that directly answers the question is highly superior and deserves a 9 or 10.
2. **PENALIZE RAMBLING AND FLUFF**: If the candidate writes a long response full of generic explanations, high-level filler, or unrelated topics, actively penalize their score. If the answer is off-topic, it must get a 1/10 or 2/10.
3. **DIRECT EVASION DETECTION**: If the candidate answers with "I don't know", "not sure", "no idea", or tries to dodge the question by changing the subject, they MUST be given a score of 1/10 or 2/10. Set strong_points to "None." and explain this evasion in weak_points.
4. **NO GENTLE GRADING**: Candidates must demonstrate deep, production-ready engineering knowledge. Be exceptionally strict. A generic or superficial answer should receive a 4/10 or 5/10.
5. **TEMPLATE CLARITY**: If the score is low (1-3/10), do not say they had a "solid start" or write false praise. Set strong_points strictly to "None." if they did not answer correctly.

Provide your evaluation ONLY as a valid JSON object matching this schema:
{{
  "score": <integer from 1 to 10>,
  "verdict": "<Strong Yes | Yes | No | Strong No>",
  "strong_points": "<specific technical elements they got right. Set strictly to 'None.' if answer is off-topic, evasive, or failed>",
  "weak_points": "<specific technical errors, conceptual gaps, missing details, or explanation of why they failed>",
  "follow_up_question": "<a precise technical follow-up exploring their weak points or redirecting them. Leave blank ONLY if score is 9 or 10>"
}}
Make sure the JSON response is perfectly formatted and does not contain conversational prefixes/suffixes."""

def run_resume_compiler(resume_text: str) -> Dict[str, Any]:
    lexer = ResumeLexer(resume_text)
    tokens = lexer.tokenize()
    
    parser = ResumeParser(tokens)
    ast = parser.parse()
    
    analyzer = SemanticAnalyzer(ast)
    semantic_data = analyzer.analyze()
    
    optimizer = IrOptimizer(semantic_data["symbol_table"])
    optimized_skills = optimizer.optimize()
    
    return {
        "email": ast.email,
        "phone": ast.phone,
        "raw_tokens_count": len(tokens),
        "ast": ast.to_dict(),
        "warnings": semantic_data["warnings"],
        "symbol_table": semantic_data["symbol_table"],
        "skills": optimized_skills
    }
