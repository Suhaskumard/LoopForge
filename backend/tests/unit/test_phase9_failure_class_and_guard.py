"""Phase 9: failure classes, the test-weakening guard and targeted Repair context."""

import pytest

from app.agents.repair_context import select_context
from app.evaluation.failure_class import STRATEGIES, classify_failure
from app.evaluation.test_guard import detect_test_weakening
from app.execution.languages import JAVASCRIPT, PYTHON

# ---- failure classes -----------------------------------------------------------------------


def f(error_type="", nodeid="tests/test_x.py::t", message="", traceback=""):
    return {
        "error_type": error_type,
        "nodeid": nodeid,
        "message": message,
        "traceback": traceback,
    }


@pytest.mark.parametrize(
    ("failures", "expected"),
    [
        ([], "logic"),
        ([f("SyntaxError")], "syntax"),
        ([f("IndentationError")], "syntax"),
        ([f("ModuleNotFoundError")], "import"),
        ([f("ImportError")], "import"),
        ([f("Timeout")], "environment"),
        ([f(nodeid="<dependencies>")], "environment"),
        ([f(nodeid="<execution>")], "environment"),
        ([f("AssertionError", traceback="app/routes.py:4: assert 404 == 200")], "logic"),
        ([f("KeyError", traceback="tests/test_x.py:9: in test_a\nKeyError: 'x'")], "test_wrong"),
        (
            [f("KeyError", traceback="app/routes.py:4: in get\ntests/test_x.py:9: KeyError")],
            "logic",
        ),
        ([f("Unknown")], "logic"),
        # the most fundamental failure wins: nothing else can be judged while the code doesn't parse
        ([f("AssertionError"), f("ImportError"), f("SyntaxError")], "syntax"),
        ([f("AssertionError"), f("ImportError")], "import"),
    ],
)
def test_python_failure_classes(failures, expected):
    assert classify_failure(failures, PYTHON) == expected


def test_javascript_failure_classes_use_message_text():
    assert classify_failure([f(message="SyntaxError: Unexpected token }")], JAVASCRIPT) == "syntax"
    assert classify_failure([f(message="Cannot find module './store'")], JAVASCRIPT) == "import"
    assert classify_failure([f("TypeError", traceback="src/app.js:3")], JAVASCRIPT) == "logic"


def test_every_class_has_a_strategy():
    assert set(STRATEGIES) == {"syntax", "import", "environment", "test_wrong", "logic"}


# ---- test-weakening guard ------------------------------------------------------------------

OLD_TEST = """
import pytest

def test_a():
    assert add(1, 2) == 3
    assert add(0, 0) == 0

def test_b():
    with pytest.raises(ValueError):
        add("x", 1)
"""


def weak(new, old=OLD_TEST, path="tests/test_x.py", profile=PYTHON):
    return detect_test_weakening({path: old}, {path: new}, profile)


def test_unchanged_or_stronger_tests_are_fine():
    assert weak(OLD_TEST) == []
    stronger = OLD_TEST + "\ndef test_c():\n    assert add(2, 2) == 4\n"
    assert weak(stronger) == []


def test_removing_a_test_is_flagged():
    findings = weak(OLD_TEST.split("def test_b")[0])
    assert any("removed test" in x and "test_b" in x for x in findings)


def test_removing_assertions_is_flagged():
    findings = weak(OLD_TEST.replace("    assert add(0, 0) == 0\n", "    pass\n"))
    assert any("assertions reduced" in x for x in findings)


@pytest.mark.parametrize(
    "marker",
    [
        "@pytest.mark.skip\n",
        "@pytest.mark.xfail\n",
        '@pytest.mark.skipif(True, reason="x")\n',
    ],
)
def test_skip_markers_are_flagged(marker):
    assert any(
        "skip/xfail" in x for x in weak(OLD_TEST.replace("def test_a", marker + "def test_a"))
    )


def test_pytest_skip_call_and_module_mark_are_flagged():
    body = OLD_TEST.replace("def test_a():\n", "def test_a():\n    pytest.skip('later')\n")
    assert any("skip/xfail" in x for x in weak(body))
    marked = "pytestmark = pytest.mark.skip\n" + OLD_TEST
    assert any("skip/xfail" in x for x in weak(marked))


def test_unparseable_edit_is_flagged_but_already_broken_file_is_ignored():
    assert any("no longer parses" in x for x in weak("def test_a(:\n"))
    assert weak(OLD_TEST, old="def broken(:\n") == []


def test_non_test_files_and_new_files_are_ignored():
    assert detect_test_weakening({"app/x.py": "a=1"}, {"app/x.py": ""}, PYTHON) == []
    assert detect_test_weakening({}, {"tests/test_new.py": "x"}, PYTHON) == []
    assert detect_test_weakening({"tests/test_x.py": "x"}, {}, PYTHON) == []  # not in the patch


JS_OLD = """
test('a', () => { expect(add(1, 2)).toBe(3); expect(add(0, 0)).toBe(0); });
test('b', () => { expect(add(2, 2)).toBe(4); });
"""


def test_javascript_guard():
    p = "src/add.test.js"
    assert weak(JS_OLD, old=JS_OLD, path=p, profile=JAVASCRIPT) == []
    fewer = JS_OLD.split("test('b'")[0]
    assert any("tests reduced" in x for x in weak(fewer, old=JS_OLD, path=p, profile=JAVASCRIPT))
    less = JS_OLD.replace("expect(add(0, 0)).toBe(0);", "")
    assert any(
        "assertions reduced" in x for x in weak(less, old=JS_OLD, path=p, profile=JAVASCRIPT)
    )
    skipped = JS_OLD.replace("test('b'", "test.skip('b'")
    assert any("skip" in x for x in weak(skipped, old=JS_OLD, path=p, profile=JAVASCRIPT))


# ---- targeted context ----------------------------------------------------------------------

FILES = {
    "app/main.py": "from app import routes\n\ndef create_app():\n    return routes\n",
    "app/routes.py": "from app.models import Employee\n\ndef update(x):\n    return Employee\n",
    "app/models.py": "class Employee:\n    pass\n",
    "app/auth.py": "def login():\n    pass\n",
    "app/__init__.py": "",
    "tests/test_routes.py": "def test_update():\n    assert True\n",
}


def test_named_file_and_its_imports_are_sent_in_full_others_are_outlined():
    text = select_context(FILES, "app/routes.py:4: assert 404 == 200", PYTHON, max_chars=10_000)
    assert "--- app/routes.py\nfrom app.models" in text
    assert "--- app/models.py\nclass Employee" in text  # direct import of the failing file
    assert "--- app/auth.py (outline only" in text and "login" in text
    assert "def login():\n    pass" not in text  # the body of an unrelated file is not sent
    assert text.index("--- app/routes.py") < text.index("--- app/auth.py")


def test_no_signal_keeps_sending_everything():
    text = select_context(FILES, "something went wrong", PYTHON, max_chars=10_000)
    assert "outline only" not in text and "def login():\n    pass" in text


def test_size_limit_omits_full_files_not_outlines():
    text = select_context(FILES, "app/routes.py", PYTHON, max_chars=10)
    assert "app/routes.py (omitted: size limit)" in text


def test_windows_separators_in_failure_text_still_match():
    text = select_context(FILES, "app\\routes.py:4", PYTHON, max_chars=10_000)
    assert "--- app/routes.py\nfrom app.models" in text


JS_FILES = {
    "src/index.js": "import { add } from './math';\nexport const run = () => add(1, 2);\n",
    "src/math.js": "export function add(a, b) { return a + b; }\n",
    "src/other.js": "export function unrelated() { return 1; }\n",
}


def test_javascript_imports_are_followed():
    text = select_context(JS_FILES, "src/index.js:2", JAVASCRIPT, max_chars=10_000)
    assert "--- src/math.js\nexport function add" in text
    assert "--- src/other.js (outline only" in text
