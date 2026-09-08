#!/usr/bin/env bash
# Start a fresh seeded backend, exercise the API end to end (login, roles, CV
# extraction, gap analysis + match score, learning, tutor, assessment, and the
# anonymized university dashboard), then stop it.
#
# Uses the token-based auth model: login returns a bearer token that gates every
# protected endpoint.
set -uo pipefail
cd "$(dirname "$0")/.."

resolve_venv_python() {
  local venv_dir="${1:-.venv}"
  local candidate=""
  for candidate in \
    "$venv_dir/Scripts/python.exe" \
    "$venv_dir/Scripts/python" \
    "$venv_dir/bin/python" \
    "$venv_dir/bin/python3"; do
    if [ -x "$candidate" ]; then
      if [ "${candidate#/}" = "$candidate" ]; then
        candidate="$PWD/$candidate"
      fi
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

VENV_DIR="${VENV_DIR:-.venv}"
VENV_PY="$(resolve_venv_python "$VENV_DIR")" || {
  echo "Virtual environment is incomplete." >&2
  exit 1
}

API="http://127.0.0.1:8000/api"
TMP=$(mktemp -d)
FAILURES=0

_run_server() {
  pkill -9 -f "uvicorn app.main" 2>/dev/null
  sleep 1
  cd backend
  rm -f skillbridge.db
  SKILLBRIDGE_DB="$PWD/skillbridge.db" "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/sb-server.log 2>&1 &
  SERVER_PID=$!
  cd ..
  for i in $(seq 1 60); do
    if curl -s -o /dev/null "$API/auth/me"; then break; fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "SERVER DIED — log:"; cat /tmp/sb-server.log; exit 1
    fi
    sleep 1
  done
}

json_field() {
  if [ "$1" = "-" ]; then
    "$VENV_PY" -c "import sys,json; print(json.load(sys.stdin)$2)"
  else
    "$VENV_PY" -c "import sys,json; print(json.load(open('$1'))$2)"
  fi
}

check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS  $label"
  else
    echo "  FAIL  $label"
    FAILURES=$((FAILURES+1))
  fi
}

login() {
  local email="$1"
  curl -s -X POST "$API/auth/login" -H "Content-Type: application/json" \
    -d "{\"email\":\"$email\",\"password\":\"demo1234\"}" | json_field "-" "['token']"
}

stop() {
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  rm -rf "$TMP"
}

_run_server
trap stop EXIT

echo "=== Auth ==="
login "aisha@student.edu" > "$TMP/aisha_tok"
AISHA_TOKEN=$(cat "$TMP/aisha_tok")
check "Student can log in (aisha@student.edu)" test -n "$AISHA_TOKEN" && test "$AISHA_TOKEN" != "None"

curl -s "$API/auth/me" -H "Authorization: Bearer $AISHA_TOKEN" > "$TMP/me"
AISHA_ID=$(json_field "$TMP/me" "['student']['id']")
check "Student /me returns own student record" test -n "$AISHA_ID" && test "$AISHA_ID" != "None"

UNAUTH_ME=$(curl -s -o /dev/null -w '%{http_code}' "$API/auth/me")
check "Unauthenticated /me is rejected (401)" test "$UNAUTH_ME" = "401"

UNAUTH_SKILLS=$(curl -s -o /dev/null -w '%{http_code}' "$API/skills")
check "Unauthenticated /api/skills is rejected (401)" test "$UNAUTH_SKILLS" = "401"

BADLOGIN=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/auth/login" \
  -H "Content-Type: application/json" -d '{"email":"aisha@student.edu","password":"wrongpass"}')
check "Wrong password is rejected (401)" test "$BADLOGIN" = "401"

login "omar@student.edu" > "$TMP/omar_tok"
OMAR_TOKEN=$(cat "$TMP/omar_tok")
check "Second student can log in (omar@student.edu)" test -n "$OMAR_TOKEN" && test "$OMAR_TOKEN" != "None"

login "hr@northstar.com" > "$TMP/company_tok"
COMPANY_TOKEN=$(cat "$TMP/company_tok")
check "Company (hr@northstar.com) can log in" test -n "$COMPANY_TOKEN" && test "$COMPANY_TOKEN" != "None"

login "admin@univ.edu" > "$TMP/admin_tok"
ADMIN_TOKEN=$(cat "$TMP/admin_tok")
check "University Admin (admin@univ.edu) can log in" test -n "$ADMIN_TOKEN" && test "$ADMIN_TOKEN" != "None"

OTHER_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$API/students/$AISHA_ID/analysis" -H "Authorization: Bearer $OMAR_TOKEN")
check "Student is scoped to their own data (cross-access rejected 403)" test "$OTHER_STATUS" = "403"

echo "=== Company defines a role ==="
curl -s "$API/auth/me" -H "Authorization: Bearer $COMPANY_TOKEN" > "$TMP/company_me"
COMPANY_ID=$(json_field "$TMP/company_me" "['company']['id']")
check "Company /me returns company record" test -n "$COMPANY_ID"

curl -s -X POST "$API/roles" -H "Authorization: Bearer $COMPANY_TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Data Platform Engineer","description":"verify script role","required_skills":[{"name":"Spark","category":"Big Data","level":"Intermediate"},{"name":"SQL","category":"Data","level":"Advanced"}]}' \
  > "$TMP/role"
ROLE_ID=$(json_field "$TMP/role" "['id']")
check "Company creates a Role with required skills" test -n "$ROLE_ID" && test "$ROLE_ID" != "None"

curl -s "$API/roles/$ROLE_ID" -H "Authorization: Bearer $COMPANY_TOKEN" > "$TMP/role_get"
ROLE_TITLE=$(json_field "$TMP/role_get" "['title']")
check "Created Role persists (title round-trips)" test "$ROLE_TITLE" = "Data Platform Engineer"

echo "=== Student uploads CV & gap analysis ==="
curl -s -X POST "$API/students/$AISHA_ID/cv" \
  -H "Authorization: Bearer $AISHA_TOKEN" \
  -F "file=@/tmp/opencode/sample_cv.txt;type=text/plain" > "$TMP/cv"
check "CV upload extracts a self-reported skill list" \
  python3 -c "import json; assert len(json.load(open('$TMP/cv'))['extracted']) > 0"

curl -s "$API/students/$AISHA_ID/analysis" -H "Authorization: Bearer $AISHA_TOKEN" > "$TMP/analysis"
check "Gap analysis returns a 0-100 match score" \
  python3 -c "import json; m=json.load(open('$TMP/analysis'))['match_score']; assert 0 <= m <= 100"
check "Gap analysis returns a non-empty skill gap map" \
  python3 -c "import json; assert len(json.load(open('$TMP/analysis'))['skill_gaps']) > 0"
GAP_SKILL=$(json_field "$TMP/analysis" "['skill_gaps'][0]['skill_id']")

echo "=== Learning path (GenAI) ==="
curl -s -X POST "$API/students/$AISHA_ID/learning/generate" \
  -H "Authorization: Bearer $AISHA_TOKEN" -H "Content-Type: application/json" \
  -d "{\"skill_id\":$GAP_SKILL}" > "$TMP/learn"
check "Learning path returns explanation+practice+mini-project" \
  python3 -c "import json; d=json.load(open('$TMP/learn')); assert d['explanation'] and d['practice_exercise'] and d['mini_project']"
check "Learning path returns a non-empty resources list" \
  python3 -c "import json; assert len(json.load(open('$TMP/learn'))['resources']) > 0"

echo "=== AI Tutor (context-injected) ==="
curl -s -X POST "$API/students/$AISHA_ID/tutor" \
  -H "Authorization: Bearer $AISHA_TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"How should I study this quickly?\",\"skill_id\":$GAP_SKILL}" > "$TMP/tutor"
check "AI Tutor returns a non-empty reply" \
  python3 -c "import json; assert json.load(open('$TMP/tutor')).get('content')"

echo "=== Proctored assessment ==="
curl -s -X POST "$API/students/$AISHA_ID/assessments/generate" \
  -H "Authorization: Bearer $AISHA_TOKEN" -H "Content-Type: application/json" \
  -d "{\"skill_id\":$GAP_SKILL,\"num_questions\":5}" > "$TMP/quiz"
check "Assessment generation returns questions" \
  python3 -c "import json; assert len(json.load(open('$TMP/quiz'))['questions']) > 0"

echo "=== University dashboard (anonymized, aggregated) ==="
curl -s "$API/university/stats" -H "Authorization: Bearer $ADMIN_TOKEN" > "$TMP/stats"
check "University stats only expose aggregates (no names/emails)" \
  python3 -c "import json; s=json.dumps(json.load(open('$TMP/stats'))).lower(); assert 'aisha@' not in s and 'omar@' not in s"
check "University stats rule states minimum cohort size" \
  python3 -c "import json; assert json.load(open('$TMP/stats'))['rule']['min_cohort_size'] >= 1"

NONADMIN_STATS=$(curl -s -o /dev/null -w '%{http_code}' "$API/university/stats" -H "Authorization: Bearer $AISHA_TOKEN")
check "Non-admin cannot read university stats (403)" test "$NONADMIN_STATS" = "403"

echo "=== Frontend served at root ==="
check "Frontend HTML served at /" bash -c "curl -s http://127.0.0.1:8000/ | grep -q '<!doctype html>'"
JS_ASSET=$(ls frontend/dist/assets 2>/dev/null | grep '\.js$' | head -1)
check "Built JS asset served (200)" bash -c \
  "[ \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/assets/$JS_ASSET) = 200 ]"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "All end-to-end API checks passed."
else
  echo "$FAILURES check(s) FAILED."
  exit 1
fi
