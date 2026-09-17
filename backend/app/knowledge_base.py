"""Small, curated CS knowledge base used by the Learning system.

This module is deliberately data-first: canonical curriculum, prerequisites, and
lesson facts live here, never in an LLM prompt.  Only entries marked ``complete``
can be served as a canonical lesson.  Planned entries document the extension
shape without pretending that their content has shipped.
"""
from copy import deepcopy
import re


KNOWLEDGE_BASE_VERSION = "cs-kb-v1"


def _key(value):
    # Competencies are persisted both as display labels and as path identifiers
    # (for example ``python_error_handling``).  Treat those representations as
    # the same canonical lookup key so a stored path cannot fall back to a
    # generic generated lesson.
    return re.sub(r"\s+", " ", str(value or "").replace("_", " ").strip()).lower()


PYTHON_FUNCTIONS = {
    "status": "complete",
    "skill_aliases": ("python", "python programming"),
    "competency": "Python Functions",
    "objective": "Define a Python function with parameters and return a reusable value.",
    "prerequisites": [
        {
            "competency": "Python values, variables, and expressions",
            "relationship": "required foundation",
            "why": "Function arguments and return values are ordinary Python values; you need to read assignments and expressions to follow a function call.",
        },
    ],
    "roadmap_rationale": (
        "Python Functions appears in this roadmap because it is the first reusable-unit skill: "
        "it lets you turn repeated steps into a named, testable behavior. The canonical Python "
        "curriculum places it after values, variables, and expressions, not because a role demands it."
    ),
    "learn": {
        "title": "Python Functions / دوال بايثون",
        "explanation": (
            "A **function** is a named recipe for a small job. `def` creates the recipe, "
            "parameters receive input, and `return` sends a result back to the caller.\n\n"
            "**بالعربية:** الدالة هي وصفة لها اسم لتنفيذ مهمة صغيرة. نستخدم `def` لتعريفها، "
            "وتستقبل المعاملات المدخلات، ثم يعيد `return` نتيجة إلى المكان الذي استدعى الدالة."
        ),
        "key_ideas": [
            "Define a function with `def name(parameters):` and an indented body.",
            "Arguments are the values supplied at a call; parameters are the names inside the definition.",
            "Use `return` when later code needs the computed value; `print` only displays text.",
            "Keep one function focused on one clear responsibility so it is easy to test and reuse.",
        ],
        "key_terms": {
            "function / دالة": "A named block of reusable code.",
            "parameter / معامل": "A variable in the function definition that receives an input.",
            "argument / قيمة مُمرّرة": "A concrete value passed when calling a function.",
            "return value / قيمة مُعادة": "The value a function sends back to its caller.",
        },
        "job_relevance": "Functions make small pieces of application, data, and automation code reusable and independently testable.",
        "common_mistake": "Do not confuse `print(total)` with `return total`: printed output cannot be used by the next line of program logic.",
        "worked_example": "The example calculates a delivery total from two inputs, then checks the returned value with several inputs.",
        "depth_note": "Canonical beginner content; it is fixed by the curated knowledge base, not generated for a target role.",
        "version_note": "Examples use Python 3 syntax and the standard library only.",
        "grounding_sources": [{"title": "Python tutorial: defining functions", "url": "https://docs.python.org/3/tutorial/controlflow.html#defining-functions", "source": "Python documentation"}],
    },
    "example": {
        "title": "A reusable delivery-total function",
        "type": "code",
        "content": (
            "def delivery_total(price, delivery_fee):\n"
            "    return price + delivery_fee\n\n"
            "assert delivery_total(20, 5) == 25\n"
            "assert delivery_total(0, 5) == 5\n"
            "assert delivery_total(12.5, 2.5) == 15.0\n\n"
            "print(delivery_total(20, 5))  # 25"
        ),
        "explanation": "`price` and `delivery_fee` are parameters. Each call provides arguments, and `return` makes the sum available to `assert` and `print`.",
    },
    "practice": {
        "type": "practical",
        "title": "Write a temperature conversion function",
        "task": "Write `celsius_to_fahrenheit(celsius)` that returns the Fahrenheit value using `(celsius * 9 / 5) + 32`. Do not print inside the function. Include your function and a short note explaining why `return` is needed.",
        "response_type": "code",
        "competency": "Python Functions",
        "starter_code": "def celsius_to_fahrenheit(celsius):\n    # write your code here\n    pass\n",
        "automated_tests": [
            {"input": [0], "expected": 32},
            {"input": [100], "expected": 212},
            {"input": [-40], "expected": -40},
            {"input": [37.5], "expected": 99.5},
        ],
    },
    "mini_check": {
        "questions": [
            {"id": "m1", "type": "mcq", "question": "Which line sends a computed value back to the caller?", "options": ["print(total)", "return total", "def total", "total = input()"], "correct_answer": "return total", "competency": "Python Functions", "difficulty": "beginner", "misconception_hint": "`print` shows a value on screen; `return` gives it back to the code that called the function."},
            {"id": "m2", "type": "mcq", "question": "In `def greet(name):`, what is `name`?", "options": ["An argument", "A parameter", "A return value", "A module"], "correct_answer": "A parameter", "competency": "Python Functions", "difficulty": "beginner", "misconception_hint": "A parameter is named in the definition; an argument is the concrete value used in a call such as `greet('Mona')`."},
            {"id": "m3", "type": "mcq", "question": "What does `delivery_total(20, 5)` evaluate to in the lesson example?", "options": ["20", "5", "25", "It only prints a value"], "correct_answer": "25", "competency": "Python Functions", "difficulty": "beginner", "misconception_hint": "The function adds both arguments and returns their sum; the caller can then use that value."},
        ]
    },
}


PYTHON_ERROR_HANDLING = {
    "status": "complete",
    "skill_aliases": ("python", "python programming"),
    "competency": "Python Error Handling",
    "objective": "Handle an expected conversion error with try/except and return a clear result.",
    "prerequisites": [{
        "competency": "Python Functions",
        "relationship": "required foundation",
        "why": "Handling an error inside a function is easier to follow after you can read parameters and return values.",
    }],
    "roadmap_rationale": "Python Error Handling follows Python Functions because programs need a safe response when real input cannot be converted or processed.",
    "learn": {
        "title": "Python Error Handling / التعامل مع أخطاء بايثون",
        "explanation": "An **exception** is Python's signal that an operation cannot continue normally. Put code that may fail in `try`; use `except ValueError` for a value in the wrong format. Handle the specific error you expect, then return a useful result instead of letting the program stop.\n\n**بالمصري:** الـ exception معناها إن بايثون قابل مشكلة. حط السطر اللي ممكن يفشل داخل `try`، ولو النص مش رقم مثلًا امسك `ValueError` في `except` وارجع نتيجة واضحة بدل ما البرنامج يقف.",
        "key_ideas": ["`try` contains an operation that may raise an exception.", "`except ValueError` handles invalid numeric text; it should not hide unrelated errors.", "Return a value from both the success and error paths so the caller can decide what to do."],
        "key_terms": {"exception / استثناء": "A runtime problem Python reports.", "try / جرّب": "The block containing an operation that may fail.", "except / تعامل مع الخطأ": "The block that handles one expected exception."},
        "job_relevance": "Programs receive incomplete and incorrectly formatted input. Specific handling keeps a small failure from crashing the whole task.",
        "common_mistake": "Do not write bare `except:` here: it can hide programming mistakes that should be fixed.",
        "worked_example": "The example turns a text age into an integer. `\"24\"` returns `24`; `\"twenty\"` returns `None` without crashing.",
        "grounding_sources": [{"title": "Python documentation: Errors and Exceptions", "url": "https://docs.python.org/3/tutorial/errors.html", "source": "Python documentation"}],
    },
    "example": {
        "title": "Convert an age safely",
        "type": "code",
        "content": "def parse_age(text):\n    try:\n        return int(text)\n    except ValueError:\n        return None\n\nprint(parse_age(\"24\"))      # 24\nprint(parse_age(\"twenty\"))  # None",
        "explanation": "`int(\"24\")` succeeds, so the function returns `24`. `int(\"twenty\")` raises `ValueError`, so the matching `except` returns `None`. The code is not executed by SkillBridge; these outputs explain Python's expected behavior.",
    },
    "practice": {
        "type": "practical", "title": "Parse a score without crashing",
        "task": "Write `parse_score(text)`. It should return `int(text)` for numeric text such as `\"85\"`. If the text is not an integer such as `\"eighty\"`, catch only `ValueError` and return `None`. Add one sentence explaining why a bare `except:` is not used.",
        "response_type": "code", "competency": "Python Error Handling",
        "starter_code": "def parse_score(text):\n    # convert text safely\n    pass\n",
        "automated_tests": [{"input": ["85"], "expected": 85}, {"input": ["0"], "expected": 0}, {"input": ["eighty"], "expected": None}],
    },
    "mini_check": {"questions": [
        {"id": "e1", "type": "mcq", "question": "Which exception does `int(\"eighty\")` raise?", "options": ["ValueError", "TypeError", "KeyError", "No exception"], "correct_answer": "ValueError", "competency": "Python Error Handling", "difficulty": "beginner", "misconception_hint": "The text is a string, but its value is not a valid integer representation."},
        {"id": "e2", "type": "mcq", "question": "What does `parse_age(\"twenty\")` return in the worked example?", "options": ["24", "None", "\"twenty\"", "The program must crash"], "correct_answer": "None", "competency": "Python Error Handling", "difficulty": "beginner", "misconception_hint": "The matching `except ValueError` returns `None`."},
        {"id": "e3", "type": "mcq", "question": "Why is `except ValueError:` safer than a bare `except:` here?", "options": ["It handles the expected invalid-number input without hiding every other bug", "It runs faster", "It converts all text to integers", "It removes the need for try"], "correct_answer": "It handles the expected invalid-number input without hiding every other bug", "competency": "Python Error Handling", "difficulty": "beginner", "misconception_hint": "Catch the error you expect; unrelated programming errors should remain visible."},
    ]},
    # Presentation-only reviewed Arabic fields.  Question answer values remain
    # canonical so a persisted Mini Check is evaluated against exactly the
    # content it was issued with.
    "locales": {
        "ar": {
            "learn": {
                "title": "التعامل مع أخطاء بايثون",
                "explanation": "الاستثناء هو إشارة من بايثون إلى أن العملية لا يمكن أن تستمر بشكل طبيعي. ضع السطر الذي قد يفشل داخل `try`، واستخدم `except ValueError` عندما تكون قيمة النص بصيغة غير صحيحة. تعامل مع الخطأ المتوقع تحديدًا، ثم أعد نتيجة مفيدة بدل أن يتوقف البرنامج.",
                "key_ideas": ["يحتوي `try` على عملية قد تثير استثناءً.", "يتعامل `except ValueError` مع النص الرقمي غير الصحيح من دون إخفاء أخطاء أخرى.", "أعد قيمة في مسار النجاح ومسار الخطأ كي يقرر المستدعي ما يفعله."],
                "key_terms": {"استثناء": "مشكلة وقت تشغيل يبلغ عنها بايثون.", "try": "كتلة تحتوي على عملية قد تفشل.", "except": "كتلة تعالج استثناءً متوقعًا."},
                "job_relevance": "تصل البرامج مدخلات ناقصة أو بصيغة خاطئة؛ التعامل المحدد مع الخطأ يمنع فشلًا صغيرًا من إيقاف المهمة كلها.",
                "common_mistake": "لا تستخدم `except:` بلا اسم هنا؛ فقد يخفي خطأً برمجيًا يجب إصلاحه.",
                "worked_example": "يحوّل المثال نص العمر إلى عدد صحيح. تعيد `\"24\"` القيمة `24`، وتعطي `\"twenty\"` القيمة `None` من دون توقف البرنامج.",
            },
            "example": {
                "title": "تحويل العمر بأمان",
                "type": "code",
                "content": "def parse_age(text):\n    try:\n        return int(text)\n    except ValueError:\n        return None\n\nprint(parse_age(\"24\"))      # 24\nprint(parse_age(\"twenty\"))  # None",
                "explanation": "ينجح `int(\"24\")` فتُعاد `24`. أما `int(\"twenty\")` فيثير `ValueError`، لذلك تعيد كتلة `except` القيمة `None`. هذا المثال للشرح؛ SkillBridge لا ينفذ هذا الكود.",
            },
            "practice": {
                "title": "حلّل درجة من دون توقف البرنامج",
                "task": "اكتب `parse_score(text)`. يجب أن تعيد `int(text)` للنص الرقمي مثل `\"85\"`. إذا لم يكن النص عددًا صحيحًا مثل `\"eighty\"`، التقط `ValueError` فقط وأعد `None`. أضف جملة تشرح لماذا لا نستخدم `except:` بلا اسم.",
            },
        },
    },
}


# These declarations reserve stable identifiers and schema for later curation.
# They are intentionally not served as lessons and must not be described as complete.
PLANNED_TOPICS = {
    ("sql", "joins"): {"status": "planned", "competency": "Joins", "prerequisites": ["Queries & filtering"], "content": None},
    ("machine learning", "evaluation basics"): {"status": "planned", "competency": "Evaluation basics", "prerequisites": ["Training a first model"], "content": None},
}


def complete_lesson(skill_name, competency):
    """Return a deep copy of canonical complete content, or ``None``."""
    if _key(skill_name) in PYTHON_FUNCTIONS["skill_aliases"] and _key(competency) == "python functions":
        return deepcopy(PYTHON_FUNCTIONS)
    if _key(skill_name) in PYTHON_ERROR_HANDLING["skill_aliases"] and _key(competency) in ("python error handling", "error handling"):
        return deepcopy(PYTHON_ERROR_HANDLING)
    return None


def prerequisites_for(skill_name, competency):
    topic = complete_lesson(skill_name, competency)
    return topic["prerequisites"] if topic else []
