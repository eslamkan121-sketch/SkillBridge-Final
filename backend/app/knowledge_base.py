"""Small, curated CS knowledge base used by the Learning system.

This module is deliberately data-first: canonical curriculum, prerequisites, and
lesson facts live here, never in an LLM prompt.  Only entries marked ``complete``
can be served as a canonical lesson.  Planned entries document the extension
shape without pretending that their content has shipped.
"""
from copy import deepcopy
import re


KNOWLEDGE_BASE_VERSION = "cs-kb-v2"


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
        "title": "Python Functions",
        "explanation": (
            "A **function** is a named recipe for a small job. `def` creates the recipe, "
            "parameters receive input, and `return` sends a result back to the caller."
        ),
        "key_ideas": [
            "Define a function with `def name(parameters):` and an indented body.",
            "Arguments are the values supplied at a call; parameters are the names inside the definition.",
            "Use `return` when later code needs the computed value; `print` only displays text.",
            "Keep one function focused on one clear responsibility so it is easy to test and reuse.",
        ],
        "key_terms": {
            "function": "A named block of reusable code.",
            "parameter": "A variable in the function definition that receives an input.",
            "argument": "A concrete value passed when calling a function.",
            "return value": "The value a function sends back to its caller.",
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
            {"id": "m1", "type": "mcq", "question": "Which line sends a computed value back to the caller?", "options": ["print(total)", "return total", "def total", "total = input()"], "correct_answer": "return total", "competency": "Python Functions", "difficulty": "beginner", "misconception_hint": "Compare what each construct does after the function call finishes."},
            {"id": "m2", "type": "mcq", "question": "In `def greet(name):`, what is `name`?", "options": ["An argument", "A parameter", "A return value", "A module"], "correct_answer": "A parameter", "competency": "Python Functions", "difficulty": "beginner", "misconception_hint": "Look at whether the name appears in the definition or at a call site."},
            {"id": "m3", "type": "mcq", "question": "What does `delivery_total(20, 5)` evaluate to in the lesson example?", "options": ["20", "5", "25", "It only prints a value"], "correct_answer": "25", "competency": "Python Functions", "difficulty": "beginner", "misconception_hint": "Follow the arithmetic in the function body using both supplied values."},
        ]
    },
    # Display translations deliberately retain canonical English answer values.
    # The client uses these question strings/options only for presentation; the
    # persisted Mini Check continues to grade its immutable canonical set.
    "locales": {
        "ar": {
            "learn": {
                "title": "دوال بايثون",
                "explanation": "الدالة هي وصفة لها اسم لمهمة صغيرة. نستخدم `def` لتعريفها، والمعاملات تستقبل المدخلات، و`return` يرجّع النتيجة للكود الذي استدعى الدالة.",
                "key_ideas": ["عرّف الدالة بـ `def name(parameters):` واكتب جسمها بمسافة بادئة.", "المعامل اسمه داخل تعريف الدالة، أما القيمة التي نمررها عند الاستدعاء فهي argument.", "استخدم `return` عندما يحتاج الكود التالي للنتيجة؛ `print` يعرضها فقط."],
                "key_terms": {"دالة": "كتلة كود لها اسم ويمكن إعادة استخدامها.", "معامل": "اسم داخل تعريف الدالة يستقبل مدخلاً.", "قيمة مُعادة": "قيمة ترسلها الدالة إلى المستدعي."},
                "job_relevance": "الدوال تجعل أجزاء الكود في التطبيقات والتحليل والأتمتة قابلة لإعادة الاستخدام والاختبار.",
                "common_mistake": "لا تخلط بين `print(total)` و`return total`: الأولى تعرض القيمة فقط، والثانية تسمح للكود التالي باستخدامها.",
                "worked_example": "المثال يحسب إجمالي التوصيل من سعر ورسوم، ثم يتحقق من القيمة المعادة بأكثر من مدخل.",
            },
            "example": {"title": "دالة قابلة لإعادة الاستخدام لحساب إجمالي التوصيل", "type": "code", "content": "def delivery_total(price, delivery_fee):\n    return price + delivery_fee\n\nassert delivery_total(20, 5) == 25\nassert delivery_total(0, 5) == 5\nassert delivery_total(12.5, 2.5) == 15.0\n\nprint(delivery_total(20, 5))  # 25", "explanation": "`price` و`delivery_fee` معاملان. كل استدعاء يمرر قيماً، و`return` يجعل المجموع متاحاً لـ `assert` و`print`."},
            "practice": {"title": "اكتب دالة لتحويل الحرارة", "task": "اكتب `celsius_to_fahrenheit(celsius)` لترجع قيمة فهرنهايت باستخدام `(celsius * 9 / 5) + 32`. لا تستخدم `print` داخل الدالة. أضف الدالة وجملة قصيرة تشرح لماذا نستخدم `return`.", "response_type": "code", "competency": "Python Functions", "starter_code": "def celsius_to_fahrenheit(celsius):\n    # اكتب الكود هنا\n    pass\n"},
            "mini_check": {"questions": [
                {"id": "m1", "question": "أي سطر يرسل قيمة محسوبة للكود اللي استدعى الدالة؟", "options": ["print(total)", "return total", "def total", "total = input()"], "misconception_hint": "قارن وظيفة كل تركيب بعد ما ينتهي استدعاء الدالة."},
                {"id": "m2", "question": "في `def greet(name):`، إيه وصف `name`؟", "options": ["قيمة مرّرتها عند الاستدعاء", "معامل في تعريف الدالة", "قيمة راجعة", "وحدة برمجية"], "misconception_hint": "بصّ: الاسم مكتوب في تعريف الدالة ولا وقت استدعائها؟"},
                {"id": "m3", "question": "إيه قيمة `delivery_total(20, 5)` في مثال الدرس؟", "options": ["20", "5", "25", "بتطبع قيمة بس"], "misconception_hint": "اتبع العملية الحسابية جوه جسم الدالة باستخدام القيمتين."},
            ]},
        },
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
        "title": "Python Error Handling",
        "explanation": "An **exception** is Python's signal that an operation cannot continue normally. Put code that may fail in `try`; use `except ValueError` for a value in the wrong format. Handle the specific error you expect, then return a useful result instead of letting the program stop.",
        "key_ideas": ["`try` contains an operation that may raise an exception.", "`except ValueError` handles invalid numeric text; it should not hide unrelated errors.", "Return a value from both the success and error paths so the caller can decide what to do."],
        "key_terms": {"exception": "A runtime problem Python reports.", "try": "The block containing an operation that may fail.", "except": "The block that handles one expected exception."},
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
        {"id": "e1", "type": "mcq", "question": "Which exception does `int(\"eighty\")` raise?", "options": ["ValueError", "TypeError", "KeyError", "No exception"], "correct_answer": "ValueError", "competency": "Python Error Handling", "difficulty": "beginner", "misconception_hint": "Consider what kind of conversion the expression attempts and why the input cannot satisfy it."},
        {"id": "e2", "type": "mcq", "question": "What does `parse_age(\"twenty\")` return in the worked example?", "options": ["24", "None", "\"twenty\"", "The program must crash"], "correct_answer": "None", "competency": "Python Error Handling", "difficulty": "beginner", "misconception_hint": "Trace the error path in the function after the conversion cannot succeed."},
        {"id": "e3", "type": "mcq", "question": "Why is `except ValueError:` safer than a bare `except:` here?", "options": ["It handles the expected invalid-number input without hiding every other bug", "It runs faster", "It converts all text to integers", "It removes the need for try"], "correct_answer": "It handles the expected invalid-number input without hiding every other bug", "competency": "Python Error Handling", "difficulty": "beginner", "misconception_hint": "Think about which problems should still be visible to the developer."},
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
                "response_type": "code", "competency": "Python Error Handling",
                "starter_code": "def parse_score(text):\n    # حوّل النص بأمان هنا\n    pass\n",
            },
            "mini_check": {"questions": [
                {"id": "e1", "question": "أي استثناء بينتج من `int(\"eighty\")`؟", "options": ["ValueError", "TypeError", "KeyError", "مفيش استثناء"], "misconception_hint": "فكّر التحويل ده بيحاول يعمل إيه وليه النص المدخل مش مناسب له."},
                {"id": "e2", "question": "إيه اللي بترجعه `parse_age(\"twenty\")` في المثال؟", "options": ["24", "None", "\"twenty\"", "البرنامج لازم يقف بخطأ"], "misconception_hint": "اتبع مسار الخطأ في الدالة بعد ما التحويل ما ينجحش."},
                {"id": "e3", "question": "ليه `except ValueError:` أأمن من `except:` من غير اسم هنا؟", "options": ["بيعالج إدخال الرقم الغلط من غير ما يخفي باقي الأخطاء", "أسرع", "بيحوّل كل النصوص لأرقام", "بيغني عن try"], "misconception_hint": "فكّر في المشاكل اللي المفروض تفضل ظاهرة للمطوّر."},
            ]},
        },
    },
}


# This is deliberately the only complete SQL topic.  The rest of the existing
# SQL blueprint remains useful for diagnostics/planning, but has no canonical
# lesson in this knowledge base and must therefore stay experimental/unverified.
SQL_QUERIES_FILTERING = {
    "status": "complete",
    "skill_aliases": ("sql", "structured query language"),
    "competency": "SQL Queries & Filtering",
    "objective": "Retrieve named columns with SELECT and narrow rows with a precise WHERE condition.",
    "prerequisites": [{
        "competency": "Tables, rows, and columns",
        "relationship": "required foundation",
        "why": "A SELECT query names columns from a table, and a WHERE condition compares values stored in its rows.",
    }],
    "roadmap_rationale": (
        "SQL Queries & Filtering is the first complete SQL topic because reliable data work starts by "
        "requesting only the columns and rows needed. Sorting, aggregation, joins, and all other SQL "
        "topics remain separately scoped and are not represented as completed lessons here."
    ),
    "learn": {
        "title": "SQL Queries & Filtering",
        "explanation": (
            "`SELECT` chooses the columns you want to read, `FROM` names the table, and `WHERE` keeps "
            "only rows that meet a condition. Start with named columns instead of `SELECT *` when you know "
            "what the task needs. A string value is written in single quotes."
        ),
        "key_ideas": [
            "`SELECT name, email` returns only those two columns, in that order.",
            "`FROM customers` identifies the table being queried.",
            "`WHERE city = 'Cairo'` filters rows; it does not change the table.",
            "Use `=` for equality and quote text values; numbers are normally written without quotes.",
        ],
        "key_terms": {
            "query": "An instruction that asks a database for data.",
            "column": "A named field such as `name` or `city` in a table.",
            "row": "One record in a table.",
            "filter": "A condition in `WHERE` that decides which rows are returned.",
        },
        "job_relevance": "Analysts and developers use small, precise queries to inspect the right records without changing source data.",
        "common_mistake": "Do not use `=` without quotes for text such as Cairo, and do not confuse `WHERE` with a command that edits rows.",
        "worked_example": "The example reads each matching customer's name and email from the `customers` table; it does not insert, update, delete, or execute anything in SkillBridge.",
        "depth_note": "Canonical SQL foundation content; it is fixed by the curated knowledge base, not generated for a target role.",
        "version_note": "Examples use standard SELECT/FROM/WHERE syntax. SkillBridge does not provide a SQL database or execute learner queries.",
        "grounding_sources": [
            {"title": "PostgreSQL documentation: Querying a Table", "url": "https://www.postgresql.org/docs/current/tutorial-select.html", "source": "PostgreSQL documentation"},
            {"title": "SQLite documentation: SELECT", "url": "https://sqlite.org/lang_select.html", "source": "SQLite documentation"},
        ],
    },
    "example": {
        "title": "Find Cairo customers",
        "type": "sql",
        "content": "SELECT name, email\nFROM customers\nWHERE city = 'Cairo';",
        "explanation": "This query asks for the `name` and `email` columns only, from rows whose `city` is exactly `Cairo`. It is a worked example, not a query that SkillBridge runs.",
    },
    "practice": {
        "type": "practical",
        "title": "Filter active Cairo customers",
        "task": "Write one read-only SQL query that returns `name` and `email` from `customers` only for rows where `city` is `Cairo` and `status` is `active`. Add one short sentence explaining what each WHERE condition filters.",
        "response_type": "sql",
        "language": "sql",
        "competency": "SQL Queries & Filtering",
        "starter_code": "SELECT name, email\nFROM customers\nWHERE city = 'Cairo'\n  AND status = 'active';",
        "evaluation_note": "SkillBridge performs a static text/structure review only: it checks for a read-only SELECT, the expected table, requested columns, and both filters. It does not connect to a database or execute SQL, so the review cannot prove runtime results.",
    },
    "mini_check": {"questions": [
        {"id": "s1", "type": "mcq", "question": "Which clause narrows a query to rows where `city` is `Cairo`?", "options": ["WHERE city = 'Cairo'", "SELECT city", "FROM Cairo", "ORDER BY city"], "correct_answer": "WHERE city = 'Cairo'", "competency": "SQL Queries & Filtering", "difficulty": "beginner", "misconception_hint": "Choose the clause whose role is deciding which records stay in the result."},
        {"id": "s2", "type": "mcq", "question": "What does `SELECT name, email` request?", "options": ["Only the name and email columns", "Every column in the table", "Only rows with an email", "A new table"], "correct_answer": "Only the name and email columns", "competency": "SQL Queries & Filtering", "difficulty": "beginner", "misconception_hint": "Distinguish a list of requested fields from a condition that filters rows."},
        {"id": "s3", "type": "mcq", "question": "Which query is a read-only request for active Cairo customers?", "options": ["SELECT name, email FROM customers WHERE city = 'Cairo' AND status = 'active';", "DELETE FROM customers WHERE city = 'Cairo';", "UPDATE customers SET status = 'active';", "INSERT INTO customers (city) VALUES ('Cairo');"], "correct_answer": "SELECT name, email FROM customers WHERE city = 'Cairo' AND status = 'active';", "competency": "SQL Queries & Filtering", "difficulty": "beginner", "misconception_hint": "Check whether the statement reads existing records or attempts to change them."},
    ]},
    "locales": {
        "ar": {
            "learn": {
                "title": "استعلامات SQL والتصفية",
                "explanation": "`SELECT` بتحدد الأعمدة اللي عايز تقراها، و`FROM` بتحدد الجدول، و`WHERE` بتحتفظ بالصفوف اللي تحقق شرط. لما تعرف الأعمدة المطلوبة، سمِّيها بدل `SELECT *`. النصوص بتتكتب بين علامتي اقتباس مفردتين.",
                "key_ideas": ["`SELECT name, email` بترجع العمودين دول فقط وبالترتيب ده.", "`FROM customers` بتحدد الجدول اللي بنسأل عنه.", "`WHERE city = 'Cairo'` بتفلتر الصفوف ولا تعدّل الجدول.", "استخدم `=` للمساواة وحط النص بين اقتباس مفرد؛ الأرقام غالباً من غير اقتباس."],
                "key_terms": {"استعلام": "تعليمة بتطلب بيانات من قاعدة البيانات.", "عمود": "حقل له اسم مثل `name` أو `city` داخل جدول.", "صف": "سجل واحد داخل الجدول.", "تصفية": "شرط في `WHERE` يحدد الصفوف الراجعة."},
                "job_relevance": "المحللون والمطورون يستخدمون استعلامات صغيرة ودقيقة لقراءة السجلات المطلوبة من غير تعديل البيانات المصدرية.",
                "common_mistake": "ما تكتبش نص مثل Cairo من غير اقتباس، وما تخلطش بين `WHERE` وبين أمر بيعدّل الصفوف.",
                "worked_example": "المثال بيقرأ الاسم والبريد للعملاء المطابقين من جدول `customers`؛ SkillBridge لا ينفذ الاستعلام ولا يعدّل بيانات.",
                "depth_note": "محتوى تأسيسي ثابت لـ SQL من قاعدة المعرفة المراجَعة، وليس محتوى مولداً حسب الوظيفة.",
                "version_note": "الأمثلة تستخدم صياغة SELECT/FROM/WHERE القياسية. SkillBridge لا يوفر قاعدة بيانات SQL ولا ينفذ استعلامات المتعلم.",
            },
            "example": {"title": "ابحث عن عملاء القاهرة", "type": "sql", "content": "SELECT name, email\nFROM customers\nWHERE city = 'Cairo';", "explanation": "الاستعلام يطلب عمودي `name` و`email` فقط من الصفوف اللي قيمة `city` فيها Cairo. ده مثال للشرح وليس استعلاماً ينفذه SkillBridge."},
            "practice": {"title": "فلتر العملاء النشطين في القاهرة", "task": "اكتب استعلام SQL واحد للقراءة فقط يرجع `name` و`email` من `customers` للصفوف اللي `city` فيها Cairo و`status` فيها active. أضف جملة قصيرة تشرح كل شرط في WHERE بيصفي إيه.", "response_type": "sql", "language": "sql", "competency": "SQL Queries & Filtering", "starter_code": "SELECT name, email\nFROM customers\nWHERE city = 'Cairo'\n  AND status = 'active';", "evaluation_note": "SkillBridge يعمل مراجعة ثابتة للنص والبنية فقط: بيتأكد من SELECT للقراءة، والجدول، والأعمدة، والشرطين. لا يتصل بقاعدة بيانات ولا ينفذ SQL، لذلك المراجعة لا تثبت نتيجة وقت التشغيل."},
            "mini_check": {"questions": [
                {"id": "s1", "question": "أي جزء بيحدد الصفوف اللي `city` فيها Cairo؟", "options": ["WHERE city = 'Cairo'", "SELECT city", "FROM Cairo", "ORDER BY city"], "misconception_hint": "اختار الجزء اللي وظيفته يقرر السجلات اللي تفضل في النتيجة."},
                {"id": "s2", "question": "`SELECT name, email` بيطلب إيه؟", "options": ["عمودي الاسم والبريد بس", "كل أعمدة الجدول", "الصفوف اللي فيها بريد بس", "جدول جديد"], "misconception_hint": "فرّق بين قائمة أعمدة بنطلبها وشرط بيصفي الصفوف."},
                {"id": "s3", "question": "أي استعلام للقراءة بس عن عملاء القاهرة النشطين؟", "options": ["SELECT name, email FROM customers WHERE city = 'Cairo' AND status = 'active';", "DELETE FROM customers WHERE city = 'Cairo';", "UPDATE customers SET status = 'active';", "INSERT INTO customers (city) VALUES ('Cairo');"], "misconception_hint": "شوف الاستعلام بيقرأ سجلات موجودة ولا بيحاول يغيرها."},
            ]},
        },
    },
}


def curated_diagnostic_questions(skill_name, competencies):
    """Return reviewed diagnostic questions for complete curated topics.

    Questions are authored against one canonical competency each.  This is
    intentionally narrower than the general skill-level bank: callers must
    never tag a question about one Python topic as another merely for coverage.
    """
    requested = {_key(item) for item in (competencies or [])}
    skill_key = _key(skill_name)
    banks = {
        "python functions": [
            {"type": "mcq", "question": "In `def add(a, b): return a + b`, what does `return` do?", "options": ["Displays the sum only", "Sends the sum back to the caller", "Defines a parameter", "Stops Python forever"], "correct_answer": "Sends the sum back to the caller", "competency": "python_functions", "difficulty": "beginner"},
            {"type": "mcq", "question": "In `def greet(name):`, `name` is a:", "options": ["parameter", "argument", "module", "exception"], "correct_answer": "parameter", "competency": "python_functions", "difficulty": "beginner"},
            {"type": "mcq", "question": "Which call correctly supplies two arguments to `delivery_total(price, delivery_fee)`?", "options": ["delivery_total(20, 5)", "delivery_total(price)", "def delivery_total(20, 5)", "return delivery_total"], "correct_answer": "delivery_total(20, 5)", "competency": "python_functions", "difficulty": "beginner"},
        ],
        "python error handling": [
            {"type": "mcq", "question": "Which exception can `int(\"eighty\")` raise?", "options": ["ValueError", "KeyError", "ImportError", "No exception"], "correct_answer": "ValueError", "competency": "python_error_handling", "difficulty": "beginner"},
            {"type": "mcq", "question": "Where should `int(text)` go when it may fail because the text is not numeric?", "options": ["Inside `try`", "Only inside `except ValueError`", "After `return None`", "Inside a bare `except`"], "correct_answer": "Inside `try`", "competency": "python_error_handling", "difficulty": "beginner"},
            {"type": "mcq", "question": "Why catch `ValueError` rather than using bare `except:` in `parse_score`?", "options": ["It handles invalid numeric text without hiding unrelated bugs", "It converts every string", "It avoids using return", "It executes faster"], "correct_answer": "It handles invalid numeric text without hiding unrelated bugs", "competency": "python_error_handling", "difficulty": "beginner"},
        ],
    }
    if skill_key in PYTHON_FUNCTIONS["skill_aliases"]:
        out = []
        for key, questions in banks.items():
            if key in requested:
                out.extend(questions)
        return deepcopy(out)
    if skill_key in SQL_QUERIES_FILTERING["skill_aliases"] and any(
            key in requested for key in ("queries & filtering", "sql queries & filtering", "sql queries filtering")):
        return deepcopy([
            {"type": "mcq", "question": "Which clause filters rows to customers in Cairo?", "options": ["WHERE city = 'Cairo'", "SELECT city", "FROM Cairo", "ORDER BY city"], "correct_answer": "WHERE city = 'Cairo'", "competency": "sql_queries_filtering", "difficulty": "beginner"},
            {"type": "mcq", "question": "What does `SELECT name, email` return?", "options": ["The name and email columns", "Every column", "Only rows with email", "A new table"], "correct_answer": "The name and email columns", "competency": "sql_queries_filtering", "difficulty": "beginner"},
            {"type": "mcq", "question": "Which query reads active Cairo customers without changing data?", "options": ["SELECT name, email FROM customers WHERE city = 'Cairo' AND status = 'active';", "DELETE FROM customers WHERE city = 'Cairo';", "UPDATE customers SET status = 'active';", "INSERT INTO customers (city) VALUES ('Cairo');"], "correct_answer": "SELECT name, email FROM customers WHERE city = 'Cairo' AND status = 'active';", "competency": "sql_queries_filtering", "difficulty": "beginner"},
        ])
    return []


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
    if _key(skill_name) in SQL_QUERIES_FILTERING["skill_aliases"] and _key(competency) in (
            "queries & filtering", "sql queries & filtering", "sql queries filtering"):
        return deepcopy(SQL_QUERIES_FILTERING)
    return None


def prerequisites_for(skill_name, competency):
    topic = complete_lesson(skill_name, competency)
    return topic["prerequisites"] if topic else []
