"""SkillBridge Practice Scenarios.

Branching, evidence-driven career scenarios that let students apply what they
learned in realistic professional situations. The scenario engine lives here;
the multi-family catalog (data, software, AI, cloud/DevOps, marketing, finance,
design, project & operations management + the original security scenarios) lives
in ``scenario_catalog.py`` so future families can be added without touching the
engine.

Availability (supersedes the Phase-2 domain gate):
- A scenario is shown/startable when it is genuinely relevant to the student's
  target role:
    * the student's target role resolves to the scenario's family
      (``family_for_role``), OR
    * ``role_intent.classify_title(target, scenario.role_title)`` is EXACT /
      CLOSE / FAMILY (the same classifier the live-jobs feed obeys).
- Target roles that resolve to NO family get a deterministic set of role-specific
  blueprint scenarios cloned from the role's own required skills (never a
  security scenario) — see ``_blueprints_for`` / ``scenario_catalog``.
- Every scenario carries a ``version``; it is persisted with each attempt so the
  results stay honest if a catalog revision later changes the scenario.

Non-scope guarantees (mirror practice.py / diagnostics.py conventions):
- Scenario performance improves a student's self-reported confidence only; it
  NEVER verifies a skill and never replaces the Final Assessment.
- Scores are learned for an outcome; mistakes get feedback and the scenario is
  allowed to continue whenever the story makes sense.
"""
from . import matching, models, role_intent, scenario_catalog
import re

# Token helpers for the family term fallback (see _family_by_terms). Generic job
# tails never decide a family, so "Architectural Designer" does not fall into
# the design family just because its title contains "designer".
_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENERIC_TITLE_TAILS = frozenset({
    "analyst", "architect", "assistant", "associate", "consultant", "coordinator",
    "designer", "developer", "director", "engineer", "executive", "head", "intern",
    "lead", "manager", "officer", "operator", "owner", "recruiter", "representative",
    "specialist", "strategist", "supervisor", "technician", "writer",
})

# ---------------------------------------------------------------- thresholds

GOOD_SCORE = 70          # component at/above this upgrades self-reported confidence
HINT_PENALTY = 3         # points removed from the overall score per hint used
HINT_PENALTY_CAP = 9

# -------------------------------------------------- domain-gating (availability)
#
# A scenario is only shown/startable when it is genuinely relevant to the
# student's target role (guide §"Target roles must not see security scenarios"):
#   family match  — family_for_role(target) resolves to the scenario's family
#                   (curated title map → catalog family vocabularies → the
#                   role_intent family translated onto catalog families).
#   intent match  — role_intent.classify_title(target, scenario.role_title) is
#                   EXACT / CLOSE / FAMILY (same classifier the live-jobs feed
#                   obeys), so e.g. yara's "Cybersecurity Analyst" stays
#                   eligible even if her family resolver were ever ambiguous.
# Roles with NO family get role-specific blueprint practice cloned from the
# role's own required skills (see _blueprints_for / scenario_catalog), so a
# "Dentist (General Practice)" profile sees dental practice, never a SIEM.
# The old Path B (inverse-document-frequency specificity floor) was removed:
# a Product Analyst must never see a SIEM scenario because their CV lists SQL."""


# ------------------------------------------------------------------- design

DIFFICULTIES = {
    "beginner": {"label": "Beginner", "icon": "🟢"},
    "intermediate": {"label": "Intermediate", "icon": "🟡"},
    "advanced": {"label": "Advanced", "icon": "🔴"},
}

# Full union of facet categories across every scenario family (owned by the
# scenario catalog so a new family can ship its own facets without touching
# this module; PHASES stay static — a family scenario reuses the same narrative
# phase vocabulary).
CATEGORIES = scenario_catalog.CATEGORIES

PHASES = [
    {"key": "detection", "label": "Detection", "icon": "🔔"},
    {"key": "investigation", "label": "Investigation", "icon": "🔍"},
    {"key": "analysis", "label": "Analysis", "icon": "🧠"},
    {"key": "containment", "label": "Containment", "icon": "🚨"},
    {"key": "escalation", "label": "Escalation", "icon": "📢"},
    {"key": "resolution", "label": "Resolution", "icon": "📋"},
]

COMPONENTS = ("investigation", "decision_making", "threat_analysis", "incident_response")
COMPONENT_WEIGHTS = {
    "investigation": 30,
    "decision_making": 25,
    "threat_analysis": 25,
    "incident_response": 20,
}
COMPONENT_LABELS = {
    "investigation": "Investigation",
    "decision_making": "Decision Making",
    "threat_analysis": "Threat Analysis",
    "incident_response": "Incident Response",
}

OUTCOME_BAD = "bad"
OUTCOME_GOOD = "good"


# ------------------------------------------------------- scenario definitions

# Evidence items: {"id", "tab", "icon", "title", "content": [{"label","value"}],
#                  "component": "investigation"|"threat_analysis", "points"}
# Choice decisions: {"id", "label", "icon", "next", "points", "component", "verdict", "feedback", "consequence"}
# Multi steps: {"multi": True, "component", "options": [{"id","label","good","points"}], "after"}

# The original three cybersecurity scenarios remain the Security family.
_CORE_SCENARIOS = [
    {
        "id": "suspicious-login-001",
        "title": "Suspicious Login Investigation",
        "description": "A security alert shows multiple failed login attempts followed by a successful login from an unfamiliar location. Determine whether the account is compromised.",
        "role_title": "Cybersecurity Analyst",
        "family": "security",
        "role_families": ["security"],
        "version": scenario_catalog.SCENARIO_VERSION,
        "difficulty": "intermediate",
        "estimated_minutes": 15,
        "category": "threat_detection",
        "intro": (
            "You are a Junior Cybersecurity Analyst at TechCorp. Your SIEM has detected 47 failed login "
            "attempts followed by a successful login from an unfamiliar IP address. The account belongs to "
            "sarah.johnson, a Finance Manager with access to sensitive company data."
        ),
        "skills": ["Threat Detection", "Log Analysis", "Investigation", "Decision Making"],
        "skills_components": {
            "Threat Detection": "threat_analysis",
            "Log Analysis": "investigation",
            "Investigation": "investigation",
            "Decision Making": "decision_making",
            "Incident Response": "incident_response",
        },
        "start_step": "step-1",
        "steps": [
            {
                "id": "step-1",
                "title": "SIEM Alert",
                "phase": "detection",
                "hint": "Think about what happened immediately before the successful login. The answer usually lives in the logs before you act on the IP.",
                "situation": (
                    "The SIEM fired a High alert for sarah.johnson: 47 failed login attempts in 12 minutes, "
                    "followed by a successful login at 02:43 AM from 185.x.x.x. You have not touched the account yet."
                ),
                "evidence": [
                    {"id": "auth-log", "tab": "Authentication Logs", "icon": "📋", "component": "investigation", "points": 6,
                     "title": "AUTHENTICATION LOG", "content": [
                         {"label": "User", "value": "sarah.johnson"}, {"label": "Department", "value": "Finance"},
                         {"label": "Failed login attempts", "value": "47 in 12 minutes"},
                         {"label": "Successful login", "value": "Yes"}, {"label": "Source IP", "value": "185.x.x.x"},
                         {"label": "Location", "value": "Unknown"}, {"label": "Time", "value": "02:43 AM"},
                     ]},
                    {"id": "user-info", "tab": "User Information", "icon": "👤", "component": "investigation", "points": 4,
                     "title": "USER RECORD", "content": [
                         {"label": "Name", "value": "Sarah Johnson"}, {"label": "Role", "value": "Finance Manager"},
                         {"label": "Data access", "value": "Invoices, payroll, bank details"},
                         {"label": "Last sign-in location", "value": "Birmingham, UK (work desktop)"},
                         {"label": "MFA enrolled", "value": "Yes, app-based"},
                     ]},
                    {"id": "network-activity", "tab": "Network Activity", "icon": "🌐", "component": "threat_analysis", "points": 6,
                     "title": "NETWORK ACTIVITY — 02:43 AM", "content": [
                         {"label": "Protocol", "value": "RDP (3389) inbound"}, {"label": "Corporate VPN", "value": "Not used"},
                         {"label": "Asset", "value": "HR-023 (sarah's laptop)"},
                         {"label": "Source", "value": "185.x.x.x — no GeoIP record in your tenant"},
                         {"label": "Outbound after login", "value": "Two HTTP requests to 185.x.x.x"},
                     ]},
                ],
                "decisions": [
                    {"id": "investigate-logs", "label": "Investigate authentication logs", "icon": "🔍", "next": "step-2",
                     "points": 10, "component": "decision_making", "verdict": "good",
                     "feedback": "Reviewing the logs before touching the account is the right first move. The pattern tells you what happened before you change anything.",
                     "consequence": "The logs point to a likely credential-stuffing attempt followed by a suspicious session."},
                    {"id": "block-ip-now", "label": "Block the source IP immediately", "icon": "🚫", "next": "step-2",
                     "points": 4, "component": "decision_making", "verdict": "neutral",
                     "feedback": "Blocking feels decisive but acting before confirming you understand the incident can hide evidence and break legitimate services. Confirm the logs first, then block with a documented reason.",
                     "consequence": "The IP belongs to a shared hosting range — you gained time but still lack evidence about the session itself."},
                    {"id": "contact-user", "label": "Contact the user first", "icon": "📞", "next": "step-2",
                     "points": 4, "component": "decision_making", "verdict": "neutral",
                     "feedback": "Talking to the user is useful. Do it while the logs are still being reviewed so you can act on facts in both directions.",
                     "consequence": "Sarah is asleep and unreachable at 02:43 AM; the alert is still unresolved."},
                    {"id": "ignore-alert", "label": "Ignore the alert", "icon": "😅", "next": "outcome:exposure",
                     "points": 0, "component": "decision_making", "verdict": "bad",
                     "feedback": "A High alert with 47 failures followed by a successful login is one of the classic compromise signals. Ignoring it gives the attacker exactly what they want: quiet.",
                     "consequence": "Within 24 hours the finance mailbox rules forward invoices to an external address. You now own a data-exfiltration incident."},
                ],
            },
            {
                "id": "step-2",
                "title": "Review the Logs",
                "phase": "investigation",
                "hint": "Compare where the login came from with where the user actually is. Do the two facts agree?",
                "situation": (
                    "Deeper log review shows the successful login happened 32 minutes after the attack run. "
                    "The session did not use the corporate VPN, and the physical token (phone) that should "
                    "approve MFA was last used 9 hours earlier in the Birmingham office."
                ),
                "evidence": [
                    {"id": "log-review", "tab": "Authentication Logs", "icon": "📋", "component": "investigation", "points": 6,
                     "title": "DETAILED AUTHENTICATION LOG", "content": [
                         {"label": "12:03 AM", "value": "Failed (wrong password) x14 — IP 45.x.x.x"},
                         {"label": "02:11 AM", "value": "Failed (wrong password) x33 — IP 185.x.x.x"},
                         {"label": "02:43 AM", "value": "SUCCESS — IP 185.x.x.x, RDP session"},
                         {"label": "MFA method", "value": "Push approved — 23 seconds after prompt"},
                         {"label": "Geolocation check", "value": "Login IP resolves to the same region as the office — but the office was closed"},
                     ]},
                    {"id": "travel-pattern", "tab": "User Information", "icon": "👤", "component": "threat_analysis", "points": 6,
                     "title": "IMPOSSIBLE TRAVEL CHECK", "content": [
                         {"label": "Phone last unlock", "value": "Birmingham, UK — 17:40 (previous day)"},
                         {"label": "Login push approved", "value": "02:43 AM — no travel is possible in 9 hours"},
                         {"label": "Verdict", "value": "The MFA approval was likely social-engineered or cloned — treat the login as compromised"},
                     ]},
                ],
                "decisions": [
                    {"id": "check-endpoint", "label": "Check endpoint activity on HR-023", "icon": "💻", "next": "step-3",
                     "points": 10, "component": "threat_analysis", "verdict": "good",
                     "feedback": "You connected the impossible travel to the endpoint. That is exactly what to verify next: what ran on the machine during this session.",
                     "consequence": "Endpoint logs reveal a scheduled task spawning a network script."},
                    {"id": "reset-password", "label": "Force a password reset now", "icon": "🔑", "next": "step-3",
                     "points": 6, "component": "threat_analysis", "verdict": "neutral",
                     "feedback": "Resetting is correct eventually, but you reset the same account the attacker may be using — without looking at the endpoint first you delete evidence (lateral history, persistence).",
                     "consequence": "The reset locks the attacker out briefly but they still have plant access to HR-023."},
                    {"id": "escalate-now", "label": "Escalate to the on-call security team", "icon": "📢", "next": "step-3",
                     "points": 6, "component": "threat_analysis", "verdict": "neutral",
                     "feedback": "Escalation is fine, but the on-call team will ask for the same evidence you are about to collect. Gather the endpoint facts first so your handoff is complete.",
                     "consequence": "The team acknowledges but can act only after you provide endpoint evidence."},
                ],
            },
            {
                "id": "step-3",
                "title": "Endpoint Activity",
                "phase": "investigation",
                "hint": "An attacker who got in usually wants to stay in. Look for scheduled jobs or outbound connections that repeat.",
                "situation": (
                    "Endpoint telemetry for HR-023 shows a newly created scheduled task (LegitUpdater) that "
                    "launches a script every 30 minutes, and two outbound connections to 185.x.x.x on a "
                    "non-standard port immediately after the successful login."
                ),
                "evidence": [
                    {"id": "endpoint-log", "tab": "Endpoint Activity", "icon": "💻", "component": "investigation", "points": 6,
                     "title": "ENDPOINT ACTIVITY — HR-023", "content": [
                         {"label": "Task created", "value": "LegitUpdater — 02:44 AM (1 minute after login)"},
                         {"label": "Runs", "value": "Every 30 minutes"}, {"label": "Command", "value": "powershell -enc BQB... (obfuscated)"},
                         {"label": "Parent process", "value": "explorer.exe (spawned by session 185.x.x.x)"},
                         {"label": "Outbound", "value": "45.135.x.x:4444 — 2 connections, 3.1 KB total"},
                     ]},
                    {"id": "malware-indicator", "tab": "Threat Intel", "icon": "🛡", "component": "threat_analysis", "points": 6,
                     "title": "THREAT INTEL MATCH", "content": [
                         {"label": "Task name", "value": "LegitUpdater matches a known persistence technique"},
                         {"label": "Beacon profile", "value": "30-minute interval, small payload — consistent with C2"},
                         {"label": "File hash", "value": "SHA256 starts 6f7a2c1d — no prior positives, treat as unknown"},
                     ]},
                ],
                "decisions": [
                    {"id": "contain-device", "label": "Contain the device (disconnect from the network)", "icon": "🚨", "next": "step-4",
                     "points": 10, "component": "incident_response", "verdict": "good",
                     "feedback": "Disconnecting the asset breaks the beacon immediately and limits lateral movement. This is the right containment call after you confirmed persistence.",
                     "consequence": "The beacon stops. You can now investigate the collected payload safely."},
                    {"id": "scan-and-monitor", "label": "Run a scan and keep monitoring", "icon": "🔎", "next": "step-4",
                     "points": 5, "component": "incident_response", "verdict": "neutral",
                     "feedback": "Monitoring has a place, but the evidence already shows persisted execution and C2-style traffic. A reactive scan lets the beacon keep dialing out.",
                     "consequence": "The endpoint sends two more beacon packets before you act."},
                    {"id": "ignore-malware", "label": "Treat the alert as a false positive", "icon": "😅", "next": "outcome:exposure",
                     "points": 0, "component": "incident_response", "verdict": "bad",
                     "feedback": "A scheduled, obfuscated task created seconds after an impossible-travel login is not a false positive. This is textbook persistence.",
                     "consequence": "The account is used to reach finance data; the mailbox gets rules re-forwarding invoices."},
                ],
            },
            {
                "id": "step-4",
                "title": "Contain the Incident",
                "phase": "containment",
                "hint": "End the incident with an outcome that is documented, reversible where possible, and handed to the right team — not silent.",
                "situation": (
                    "The device is off the network. You have the scheduled task name, the hash of the launcher "
                    "script, and a timeline. Time to close this out responsibly."
                ),
                "evidence": [
                    {"id": "containment-plan", "tab": "Containment Steps", "icon": "📋", "component": "investigation", "points": 4,
                     "title": "CONTAINMENT CHECKLIST", "content": [
                         {"label": "Disconnect asset", "value": "Done (HR-023)"}, {"label": "Revoke session", "value": "Server side — pending"},
                         {"label": "Reset credentials", "value": "User + MFA re-enroll — pending"}, {"label": "Handoff", "value": "Evidence package — pending"},
                     ]},
                ],
                "decisions": [
                    {"id": "isolate-escalate", "label": "Escalate with a full evidence summary", "icon": "📢", "next": "outcome:contained",
                     "points": 10, "component": "decision_making", "verdict": "good",
                     "feedback": "You contained the device, then handed the security team a package (timeline, persistence, hash, IOCs). That is how professional incidents get resolved.",
                     "consequence": "The incident is contained and documented for lessons learned."},
                    {"id": "reset-and-monitor", "label": "Reset credentials and keep watching", "icon": "🔑", "next": "outcome:contained",
                     "points": 7, "component": "decision_making", "verdict": "neutral",
                     "feedback": "Resetting helps, but you resolved the account without a documented handoff. Ask who watches the next alert before you close your ticket.",
                     "consequence": "The device stays contained; the next shift is unaware the event ever happened."},
                    {"id": "do-nothing-more", "label": "Close the alert without further action", "icon": "🚪", "next": "outcome:contained",
                     "points": 0, "component": "decision_making", "verdict": "bad",
                     "feedback": "Containing the device was step one. Without revocation, credential reset, and a handoff the team cannot answer 'what happened and what is done?'.",
                     "consequence": "The session remains valid server-side and the account is still a risk."},
                ],
            },
        ],
        "outcomes": {
            "contained": {
                "key": "contained", "title": "Incident Contained", "icon": "🛡", "tone": OUTCOME_GOOD,
                "summary": "The compromised account was identified, the endpoint isolated, and the incident handed to the security team with a usable evidence package.",
            },
            "exposure": {
                "key": "exposure", "title": "Data Exfiltration", "icon": "⚠", "tone": OUTCOME_BAD,
                "summary": "A persisted beacon and mailbox forwarding led to data exfiltration before the account could be locked down. Use the decision review to see where the timeline could have turned.",
            },
        },
    },
    {
        "id": "phishing-email-001",
        "title": "Phishing Email Investigation",
        "description": "An employee reports a suspicious email that may contain a malicious link. Analyze the evidence and decide how to respond.",
        "role_title": "Cybersecurity Analyst",
        "family": "security",
        "role_families": ["security"],
        "version": scenario_catalog.SCENARIO_VERSION,
        "difficulty": "beginner",
        "estimated_minutes": 10,
        "category": "threat_detection",
        "intro": (
            "You work on the security operations desk at TechCorp. An employee, Priya Shah in Marketing, has "
            "forwarded a suspicious email she received this morning and asks, \"Is this safe to open?\""
        ),
        "skills": ["Email Security", "Threat Analysis", "Investigation", "Decision Making"],
        "skills_components": {
            "Email Security": "threat_analysis",
            "Threat Analysis": "threat_analysis",
            "Investigation": "investigation",
            "Decision Making": "decision_making",
        },
        "start_step": "step-1",
        "steps": [
            {
                "id": "step-1",
                "title": "Suspicious Email Reported",
                "phase": "detection",
                "hint": "Review the message the way an analyst would: header first, body second, links and attachments last — never click first.",
                "situation": (
                    "Priya's email is named 'Invoice #8821 — Payment Overdue' and claims to come from the "
                    "company's accounting office. It urges her to open an attachment within 24 hours."
                ),
                "evidence": [
                    {"id": "email-header", "tab": "Email Header", "icon": "📧", "component": "investigation", "points": 6,
                     "title": "MESSAGE HEADER", "content": [
                         {"label": "From", "value": "accounts@techcorp-billing.click"}, {"label": "Display name", "value": "TechCorp Accounting"},
                         {"label": "Reply-To", "value": "billing.claims@mail-tracking.top"}, {"label": "Return-path", "value": "no-reply@unknown.today"},
                         {"label": "SPF / DKIM", "value": "FAIL / none"}, {"label": "Received path", "value": "Relayed via two hosts outside the company"},
                     ]},
                    {"id": "email-body", "tab": "Email Content", "icon": "💬", "component": "threat_analysis", "points": 6,
                     "title": "EMAIL CONTENT", "content": [
                         {"label": "Subject", "value": "Invoice #8821 — Payment Overdue"},
                         {"label": "Tone", "value": "\"URGENT: your account will be suspended within 24 hours\""},
                         {"label": "Attachment", "value": "Invoice_8821.docm (2 KB)"},
                         {"label": "Link", "value": "https://track-k.click/invoice"}, {"label": "Greeting", "value": "\"Dear valued employee\""},
                     ]},
                    {"id": "sender-lookup", "tab": "Sender Address", "icon": "👤", "component": "investigation", "points": 4,
                     "title": "SENDER LOOKUP", "content": [
                         {"label": "Claimed domain", "value": "techcorp.com"}, {"label": "Actual domain", "value": "techcorp-billing.click"},
                         {"label": "Domain age", "value": "Registered 6 days ago"}, {"label": "Company mail server", "value": "techcorp.com is the only legitimate domain"},
                     ]},
                ],
                "decisions": [
                    {"id": "inspect-header", "label": "Inspect the email header", "icon": "🔍", "next": "step-2",
                     "points": 10, "component": "decision_making", "verdict": "good",
                     "feedback": "Starting with the header is the standard triage move: sender identity, authentication results, and relay path settle 80% of phishing questions.",
                     "consequence": "The header shows a spoofed sender and failing SPF/DKIM."},
                    {"id": "click-the-link", "label": "Open the link to see where it goes", "icon": "🖱", "next": "outcome:compromised",
                     "points": 0, "component": "decision_making", "verdict": "bad",
                     "feedback": "Clicking an unvetted link on a work machine is how these campaigns win. Never open suspicious links in a browser — analyze them in a safe manner first.",
                     "consequence": "The employee's workstation lands on a credential-harvesting page; the phishing is now a potential account compromise."},
                    {"id": "reply-sender", "label": "Reply to the sender for clarification", "icon": "🔁", "next": "step-2",
                     "points": 4, "component": "decision_making", "verdict": "neutral",
                     "feedback": "Engaging a suspicious sender gives them interaction signals and a real inbox. You can still keep this in mind while the header does the talking.",
                     "consequence": "The sender does not reply; the header evidence is what matters."},
                ],
            },
            {
                "id": "step-2",
                "title": "Identify the Phishing Indicators",
                "phase": "analysis",
                "multi": True,
                "component": "threat_analysis",
                "hint": "Phishing relies on urgency, mismatched identity, and unverified links or attachments. Select every indicator that is genuinely suspicious.",
                "situation": "Which of these observations are real phishing indicators for this email?",
                "evidence": [
                    {"id": "link-cloud", "tab": "Link Analysis", "icon": "🔗", "component": "threat_analysis", "points": 6,
                     "title": "LINK ANALYSIS — track-k.click/invoice", "content": [
                         {"label": "Domain", "value": "track-k.click (3 days old, no TLS cert history)"},
                         {"label": "League table", "value": "Listed on two public blocklists"},
                         {"label": "Redirect target", "value": "Login page copying TechCorp's portal (wrong URL)"},
                     ]},
                ],
                "options": [
                    {"id": "op-urgency", "label": "The message urges action within 24 hours", "good": True, "points": 5},
                    {"id": "op-sender-mismatch", "label": "The sender domain does not match the company", "good": True, "points": 5},
                    {"id": "op-link-domain", "label": "The link points to an unfamiliar, recently-registered domain", "good": True, "points": 5},
                    {"id": "op-macro-attachment", "label": "An unexpected .docm attachment", "good": True, "points": 5},
                    {"id": "op-business-hours", "label": "The email arrived during business hours", "good": False, "points": -4},
                    {"id": "op-first-name", "label": "The greeting uses the employee's first name", "good": False, "points": -4},
                ],
                "after": "step-3",
            },
            {
                "id": "step-3",
                "title": "Handle the Link and Attachment",
                "phase": "analysis",
                "hint": "You want to inspect content without executing it. What safe environment lets you observe behaviour?",
                "situation": (
                    "You have confirmed the message is a phish: spoofed sender, failing authentication, a "
                    "blocklisted link, and an unexpected macro-enabled attachment."
                ),
                "evidence": [
                    {"id": "sandbox-result", "tab": "Attachment Sandbox", "icon": "🧪", "component": "threat_analysis", "points": 6,
                     "title": "SANDBOX ANALYSIS — Invoice_8821.docm", "content": [
                         {"label": "Behaviour", "value": "Downloads a second-stage payload from track-k.click"},
                         {"label": "Persistence", "value": "Attempts to add a registry Run key"},
                         {"label": "Network", "value": "Beacons to an external IP on port 443"},
                         {"label": "Verdict", "value": "Malicious macro-enabled document"},
                     ]},
                ],
                "decisions": [
                    {"id": "sandbox-analyze", "label": "Analyze the attachment in a sandbox", "icon": "🧪", "next": "step-4",
                     "points": 10, "component": "threat_analysis", "verdict": "good",
                     "feedback": "A sandbox lets the file show its behaviour without risking the environment. This is the professional way to handle an unknown attachment.",
                     "consequence": "The sandbox confirms a malicious macro and gives you IOCs to share."},
                    {"id": "browser-open", "label": "Copy the link straight into a browser", "icon": "🖱", "next": "outcome:compromised",
                     "points": 0, "component": "threat_analysis", "verdict": "bad",
                     "feedback": "Opening a blocklisted link in a browser defeats the whole investigation. The landing page is built to capture credentials.",
                     "consequence": "The analyst machine now shows the credential-harvesting page; the browser is treated as a compromised asset."},
                    {"id": "ignore-attachment", "label": "Advise the employee to open the attachment on their phone", "icon": "📱", "next": "step-4",
                     "points": 3, "component": "threat_analysis", "verdict": "neutral",
                     "feedback": "Moving a suspicious file to another device still executes it — phones are not sandboxes. Keep the file contained and let the investigation finish.",
                     "consequence": "The employee's personal device becomes part of the incident scope."},
                ],
            },
            {
                "id": "step-4",
                "title": "Respond and Report",
                "phase": "escalation",
                "hint": "A good response protects the reporting employee AND every other inbox that received the message. What does that require?",
                "situation": "The phish is confirmed with IOCs. The message also went to nine other employees on the same list.",
                "evidence": [],
                "decisions": [
                    {"id": "report-quarantine", "label": "Report to security and block/quarantine the email", "icon": "📢", "next": "outcome:reported",
                     "points": 10, "component": "decision_making", "verdict": "good",
                     "feedback": "Quarantining the message for the whole recipient list plus sharing IOCs protects everyone. Complete and professional closure.",
                     "consequence": "The phish is blocked mail-wide and the employee gets appreciation for reporting it."},
                    {"id": "tell-ignore", "label": "Tell the employee to ignore and delete it", "icon": "🗑", "next": "outcome:reported",
                     "points": 4, "component": "decision_making", "verdict": "neutral",
                     "feedback": "Deleting one copy ignores the other nine inboxes and the mail system that let it through. Contain mail-wide before you educate.",
                     "consequence": "Other recipients receive the same phish and one of them opens it."},
                    {"id": "forward-all", "label": "Forward it to all staff as a warning", "icon": "📨", "next": "outcome:reported",
                     "points": 4, "component": "decision_making", "verdict": "neutral",
                     "feedback": "Warning examples are useful AFTER the actual message is blocked. Forwarding the live phish re-sends the malicious link company-wide.",
                     "consequence": "The example message reaches inboxes still able to click it."},
                ],
            },
        ],
        "outcomes": {
            "reported": {
                "key": "reported", "title": "Phish Reported & Contained", "icon": "🛡", "tone": OUTCOME_GOOD,
                "summary": "The phishing email was contained, IOCs captured, and the report treated as a learning win for the company.",
            },
            "compromised": {
                "key": "compromised", "title": "Account Compromised", "icon": "⚠", "tone": OUTCOME_BAD,
                "summary": "Analysing the phish unsafely turned a reportable email into an account-compromise investigation. Review the decisions to see the safer path.",
            },
        },
    },
    {
        "id": "siem-alert-001",
        "title": "SIEM Alert Investigation",
        "description": "Multiple alerts appear in the SIEM. Determine which events represent a real security threat and respond appropriately.",
        "role_title": "Cybersecurity Analyst",
        "family": "security",
        "role_families": ["security"],
        "version": scenario_catalog.SCENARIO_VERSION,
        "difficulty": "intermediate",
        "estimated_minutes": 15,
        "category": "siem_analysis",
        "intro": (
            "Your shift starts with 7 SIEM alerts on the overnight queue. They range from a signature update "
            "scan to a PowerShell execution on a workstation. Your job: decide what matters, prove it, and "
            "respond with the right severity."
        ),
        "skills": ["SIEM", "Log Analysis", "Event Correlation", "Threat Detection"],
        "skills_components": {
            "SIEM": "investigation",
            "Log Analysis": "investigation",
            "Event Correlation": "threat_analysis",
            "Threat Detection": "threat_analysis",
            "Incident Response": "incident_response",
            "Decision Making": "decision_making",
        },
        "start_step": "step-1",
        "steps": [
            {
                "id": "step-1",
                "title": "Review the Alerts",
                "phase": "detection",
                "hint": "Not every alert is equal. Look for what touches sensitive assets, what is new, and what escalates.",
                "situation": "Seven alerts are queued. You have 15 minutes before the morning team takes over. Which do you bring forward?",
                "evidence": [
                    {"id": "siem-feed", "tab": "SIEM Alert Feed", "icon": "📊", "component": "investigation", "points": 6,
                     "title": "ALERT QUEUE", "content": [
                         {"label": "A1", "value": "AV signature update completed (host: server-patch)"},
                         {"label": "A2", "value": "Repeated failed login for svc_backup from new IP (02:10–02:40)"},
                         {"label": "A3", "value": "User lockout after forgotten password (normal office hours)"},
                         {"label": "A4", "value": "PowerShell -enc execution on HR-023 (03:17)"},
                         {"label": "A5", "value": "Backup service start during maintenance window (scheduled)"},
                         {"label": "A6", "value": "Office-365 sign-in from unusual country (02:48)"},
                         {"label": "A7", "value": "Outbound traffic to host 45.135.x.x:4444 (03:19, HR-023)"},
                     ]},
                    {"id": "asset-grid", "tab": "Asset Grid", "icon": "🖥", "component": "threat_analysis", "points": 4,
                     "title": "ASSET GRID", "content": [
                         {"label": "Asset", "value": "HR-023 is a finance workstation"},
                         {"label": "Severity rules", "value": "A2, A4, A6, A7 map to your Critical playbook"},
                     ]},
                ],
                "decisions": [
                    {"id": "triage-by-risk", "label": "Triage by risk: focus on the asset and the new behaviours", "icon": "🎯", "next": "step-2",
                     "points": 10, "component": "decision_making", "verdict": "good",
                     "feedback": "You correctly prioritised alerts touching a finance workstation with new, escalating behaviours instead of scheduled noise.",
                     "consequence": "A2, A4, A6 and A7 move to the front."},
                    {"id": "process-order", "label": "Work through them in order received", "icon": "⏳", "next": "step-2",
                     "points": 5, "component": "decision_making", "verdict": "neutral",
                     "feedback": "First-come-first-served feels fair but it spends your scarce time on a signature update and a scheduled backup. Order by risk, not receipt time.",
                     "consequence": "The critical candidates wait while noise is reviewed first."},
                    {"id": "dismiss-off-hours", "label": "Dismiss anything from outside office hours", "icon": "🚮", "next": "outcome:missed",
                     "points": 0, "component": "decision_making", "verdict": "bad",
                     "feedback": "Threat actors welcome the night shift. A 02:48 logon from a foreign country on a finance account is exactly when to pay MORE attention, not less.",
                     "consequence": "The overnight compromise continues unnoticed into the morning."},
                ],
            },
            {
                "id": "step-2",
                "title": "Identify False Positives",
                "phase": "analysis",
                "multi": True,
                "component": "threat_analysis",
                "hint": "Noise is predictable and repeatable. Real threats connect an asset to behaviour that is new or unexpected.",
                "situation": "Select the events that genuinely warrant deeper investigation.",
                "evidence": [
                    {"id": "alert-detail", "tab": "Alert Detail", "icon": "📊", "component": "investigation", "points": 6,
                     "title": "ALERT CONTEXT", "content": [
                         {"label": "A2 detail", "value": "svc_backup failures then success from 203.x.x.x"},
                         {"label": "A4 detail", "value": "PowerShell -enc, parent: explorer.exe session"},
                         {"label": "A6 detail", "value": "Sign-in from Singapore; user is in the UK"},
                         {"label": "A7 detail", "value": "HR-023 → 45.135.x.x:4444, 2 small payloads"},
                 ]},
                ],
                "options": [
                    {"id": "ev-svc", "label": "A2 — repeated failed logins for svc_backup from a new IP", "good": True, "points": 6},
                    {"id": "ev-psh", "label": "A4 — PowerShell -enc execution on HR-023", "good": True, "points": 6},
                    {"id": "ev-o365", "label": "A6 — Office-365 sign-in from an unusual country", "good": True, "points": 6},
                    {"id": "ev-out", "label": "A7 — outbound traffic to 45.135.x.x:4444", "good": True, "points": 6},
                    {"id": "ev-av", "label": "A1 — AV signature update completed", "good": False, "points": -5},
                    {"id": "ev-lock", "label": "A3 — user lockout after a forgotten password", "good": False, "points": -5},
                    {"id": "ev-backup", "label": "A5 — backup start in the scheduled maintenance window", "good": False, "points": -5},
                ],
                "after": "step-3",
            },
            {
                "id": "step-3",
                "title": "Correlate the Events",
                "phase": "investigation",
                "hint": "Single alerts prove nothing. Find the thread — same account, same host, same time — that connects the critical ones.",
                "situation": (
                    "You now hold A2, A4, A6 and A7. Time to prove whether they are one incident or several."
                ),
                "evidence": [
                    {"id": "corr-log", "tab": "Correlated Logs", "icon": "🔗", "component": "investigation", "points": 6,
                     "title": "CORRELATION VIEW", "content": [
                         {"label": "02:40", "value": "svc_backup success from 203.x.x.x (A2)"},
                         {"label": "02:48", "value": "Finance user session from Singapore (A6)"},
                         {"label": "03:17", "value": "PowerShell epoch on HR-023 (A4)"},
                         {"label": "03:19", "value": "Outbound beacon to 45.135.x.x:4444 (A7)"},
                         {"label": "Shared account", "value": "hr-svc-backup used at 02:40; new session maps to same host"},
                     ]},
                    {"id": "lateral-log", "tab": "Network Activity", "icon": "🌐", "component": "threat_analysis", "points": 6,
                     "title": "NETWORK ACTIVITY", "content": [
                         {"label": "Origin", "value": "203.x.x.x (no company anywhere in its path)"},
                         {"label": "Lateral pattern", "value": "Service account → interactive session → workstation"},
                         {"label": "Outbound", "value": "45.135.x.x:4444 matches a known C2 port list"},
                     ]},
                ],
                "decisions": [
                    {"id": "correlate-across", "label": "Correlate across all logs to find the shared source", "icon": "🔗", "next": "step-4",
                     "points": 10, "component": "threat_analysis", "verdict": "good",
                     "feedback": "Connecting the service account, the foreign sign-in, the workstation script and the beacon turns four alerts into one coherent incident.",
                     "consequence": "You now have an attack chain: credential, lateral movement, persistence, exfiltration attempt."},
                    {"id": "isolate-single", "label": "Focus only on the PowerShell alert", "icon": "🔍", "next": "step-4",
                     "points": 5, "component": "threat_analysis", "verdict": "neutral",
                     "feedback": "Handling one alert misses the chain. The PowerShell makes sense only when you see the preceding account takeover on the same host.",
                     "consequence": "You contain one beacon but miss the service-account foothold behind it."},
                    {"id": "wait-for-more", "label": "Wait for more alerts before concluding anything", "icon": "⏳", "next": "step-4",
                     "points": 3, "component": "threat_analysis", "verdict": "neutral",
                     "feedback": "You already have four correlated indicators and a known C2 port. Waiting gives the attacker time without adding evidence.",
                     "consequence": "Two more beacons fire while you wait."},
                ],
            },
            {
                "id": "step-4",
                "title": "Respond to the Incident",
                "phase": "escalation",
                "hint": "Bring the attack chain to a decision-maker with evidence attached and the asset contained where possible.",
                "situation": "The chain is confirmed: compromised service account, foreign access, beaconing workstation on finance.",
                "evidence": [],
                "decisions": [
                    {"id": "escalate-package", "label": "Escalate with evidence and recommend immediate containment", "icon": "📢", "next": "outcome:escalated",
                     "points": 10, "component": "incident_response", "verdict": "good",
                     "feedback": "You escalated a proven, correlated incident with a recommended action. That gives leadership everything needed to make the call fast.",
                     "consequence": "The account is revoked and HR-023 isolated within the hour."},
                    {"id": "quarantine-only", "label": "Disconnect HR-023 and close the queue", "icon": "🔌", "next": "outcome:escalated",
                     "points": 6, "component": "incident_response", "verdict": "neutral",
                     "feedback": "Isolating the workstation is right, but the service account that started the chain is still alive. Revoke or reset it too.",
                     "consequence": "HR-023 is contained; the service account still holds a foothold."},
                    {"id": "resume-normal", "label": "Return to the queue and treat it as resolved", "icon": "🚪", "next": "outcome:escalated",
                     "points": 0, "component": "incident_response", "verdict": "bad",
                     "feedback": "You proved an attack chain and then stopped. An incident you can describe but do not act on is still an incident.",
                     "consequence": "No owner is assigned and the beacon continues overnight."},
                ],
            },
        ],
        "outcomes": {
            "escalated": {
                "key": "escalated", "title": "Incident Escalated", "icon": "📢", "tone": OUTCOME_GOOD,
                "summary": "You turned seven alerts into one correlated incident and escalated it with evidence and a recommended action.",
            },
            "missed": {
                "key": "missed", "title": "Threat Missed", "icon": "⚠", "tone": OUTCOME_BAD,
                "summary": "The overnight compromise went unnoticed until the morning shift. Review the triage decision to see what the night-shift analyst should have kept.",
            },
        },
    },
]


# Full catalog = the original Security family + every authored family scenario
# + per-student role-blueprint clones (added lazily, see _blueprints_for).
SCENARIOS = _CORE_SCENARIOS + list(scenario_catalog.FAMILY_SCENARIOS)

# Package-level registry of deterministic role-blueprint clones so a scenario
# id that was buildable for a student stays resolvable later — start-by-URL and
# resume-after-a-target-change both need _scenario() to find it again.
_BLUEPRINT_REGISTRY = {}
_BLUEPRINT_KEYS = set()


def _role_intent_family_alias(domain):
    """Translate a role_intent domain family onto the catalog's families.

    role_intent deliberately merges AI and Cloud/DevOps into ``software``; we
    only translate families the scenario catalog actually ships, leaving the
    rest (clinical, legal, architecture, healthcare, ...) unmapped so those
    titles fall through to role-specific blueprint practice.
    """
    aliases = {
        "security": "security",
        "data": "data",
        "software": "software",
        "design": "design",
        "marketing": "marketing",
        "finance": "finance",
        "product": "data",        # product analytics practice is the data family
        "project": "project_ops",
        "operations": "project_ops",
    }
    return aliases.get(domain or "")


def _family_by_terms(title):
    """Family from the catalog's term vocabularies (weakest signal, used to
    rescue specialized titles the curated map does not cover). Token-based with
    generic job tails ("analyst", "designer", "engineer", ...) excluded, so an
    "Architectural Designer" is never swept into the design family by the
    "design/designer" tail; a title must actually carry a domain token."""
    tokens = _TITLE_TOKEN_RE.findall((title or "").lower())
    domain = [t for t in tokens if t not in _GENERIC_TITLE_TAILS]
    if not domain:
        return None
    best, best_score = None, 0
    for fam, terms in scenario_catalog.FAMILY_TERMS.items():
        score = sum(1 for t in domain if t in terms)
        if score > best_score:
            best, best_score = fam, score
    return best if best_score else None


def family_for_role(title):
    """Canonical scenario-catalog family for a target-role title, or ``None``
    when the role has no scenario family (→ deterministic blueprint practice).

    Resolution order:
      1. Curated exact-title map (scenario_catalog.ROLE_FAMILY_BLUEPRINT) which
         covers every seeded catalog title and its close variants.
      2. The catalog family term vocabularies.
      3. role_intent.family_of() translated through _role_intent_family_alias.
    """
    title = (title or "").strip()
    if not title:
        return None
    fam = scenario_catalog.family_for_title(title)
    if fam:
        return fam
    fam = _family_by_terms(title)
    if fam:
        return fam
    return _role_intent_family_alias(role_intent.family_of(title))


def _blueprints_for(student):
    """Deterministic generic-family practice cloned from the target role's own
    required skills — only for roles with no resolved family (a dentist gets
    dental practice, never a SIEM scenario). Registered in the package-level
    registry so `_scenario` resolves them across requests."""
    role = (student or {}).get("target_role") or {}
    title = (role.get("title") or "").strip()
    if not title or family_for_role(title):
        return []
    slug = scenario_catalog._slugify(title)
    if slug in _BLUEPRINT_KEYS:
        return [s for s in _BLUEPRINT_REGISTRY.values() if s["role_title"] == title]
    skills = [
        (s.get("name") or "").strip()
        for s in (role.get("required_skills") or [])
        if (s.get("name") or "").strip()
    ]
    if not skills:
        return []
    clones = scenario_catalog.build_blueprint_scenarios(title, skills)
    for s in clones:
        _BLUEPRINT_REGISTRY[s["id"]] = s
    _BLUEPRINT_KEYS.add(slug)
    return clones


def lookup_scenario(student, scenario_id):
    """Resolve a scenario the student may start: any catalog scenario or their
    own role-blueprint clone. Returns ``None`` when unknown."""
    scn = _scenario(scenario_id)
    if scn:
        return scn
    return next((s for s in _blueprints_for(student) if s["id"] == scenario_id), None)


def _scenario(scenario_id):
    for scn in SCENARIOS:
        if scn["id"] == scenario_id:
            return scn
    return _BLUEPRINT_REGISTRY.get(scenario_id) or None


def _step(scenario, step_id):
    for step in scenario["steps"]:
        if step["id"] == step_id:
            return step
    return None


def _steps_total(scenario):
    return len(scenario["steps"])


def _evidence_payload(step):
    return [
        {
            "id": e["id"], "tab": e["tab"], "icon": e["icon"], "title": e["title"],
            "content": e.get("content") or [], "has_data": bool(e.get("content") or e.get("has_data")),
        }
        for e in step.get("evidence") or []
    ]


def _decision_payload(step):
    return [
        {
            "id": d["id"], "label": d["label"], "icon": d["icon"],
        }
        for d in step.get("decisions") or []
    ]


def _multi_payload(step):
    return [
        {"id": o["id"], "label": o["label"]}
        for o in step.get("options") or []
    ]


def _phase_of(scenario, step_id):
    step = _step(scenario, step_id)
    if not step:
        return PHASES[0]["key"]
    return step.get("phase") or PHASES[0]["key"]


def _phase_label(phase_key):
    for p in PHASES:
        if p["key"] == phase_key:
            return p
    return PHASES[0]


def public_scenario_card(scenario, progress):
    """progress: {status, best_score, attempts_count, last_outcome}"""
    diff = DIFFICULTIES.get(scenario.get("difficulty"), DIFFICULTIES["beginner"])
    cat = next((c for c in CATEGORIES if c["key"] == scenario.get("category")), CATEGORIES[0])
    fam = scenario.get("family")
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "description": scenario["description"],
        "role_title": scenario.get("role_title") or "",
        "difficulty": scenario.get("difficulty"),
        "difficulty_label": diff["label"],
        "difficulty_icon": diff["icon"],
        "estimated_minutes": scenario.get("estimated_minutes", 10),
        "estimated_time_label": f"~{scenario.get('estimated_minutes', 10)} min",
        "category": cat["key"],
        "category_label": cat["label"],
        "category_icon": cat["icon"],
        "family": fam,
        "family_label": scenario_catalog.FAMILY_LABEL_OF.get(fam),
        "family_icon": scenario_catalog.FAMILY_ICON_OF.get(fam),
        "version": scenario.get("version") or scenario_catalog.SCENARIO_VERSION,
        "skills": list(scenario.get("skills") or []),
        "steps_count": _steps_total(scenario),
        "status": progress["status"],
        "best_score": progress.get("best_score"),
        "attempts_count": progress.get("attempts_count", 0),
        "last_outcome_title": progress.get("last_outcome_title"),
        "last_outcome_tone": progress.get("last_outcome_tone"),
    }


def _component_label_map(scenario):
    """Family-honest labels for the engine's component keys (e.g. the data
    family renames ``threat_analysis`` to "Analysis"); defaults for unknown."""
    return scenario_catalog.family_component_labels(scenario.get("family") or "")


def _skill_overlap(student, scenario_skills):
    names = {
        (s.get("name") or "").lower().strip()
        for s in (student.get("self_reported_skills") or [])
    }
    names.update(
        (s.get("name") or "").lower().strip()
        for s in (student.get("verified_skills") or [])
    )
    return sum(1 for sk in scenario_skills if sk.lower().strip() in names)


# ------------------------------------------------------------ domain-gating

def scenario_eligible(student, scenario):
    """Relevance-gate a single scenario for a student (guide §"Target roles
    must not see security scenarios").

    A scenario is shown/startable when the student has a target role AND either
    the role resolves to the scenario's family or the existing title classifier
    sees EXACT / CLOSE / FAMILY overlap. Role-blueprint clones (family
    ``generic``) are always eligible for the role they were built from.
    """
    if not student:
        return False
    target = (student.get("target_role") or {}).get("title") or ""
    target = target.strip()
    if not target:
        return False
    if scenario.get("family") == "generic":
        return scenario.get("role_title") == target
    fam = family_for_role(target)
    if fam is not None:
        # Strict per-family isolation: a resolved family opens ONLY that
        # family's scenarios (an AI Engineer never sees DevOps content).
        return scenario.get("family") == fam
    # No resolved family (dentist, clinical, legal, ...): only the trained
    # title classifier may still see overlap, and those roles also get their
    # own blueprints. Never another domain by accident.
    return role_intent.classify_title(target, scenario.get("role_title") or "") != "UNRELATED"


def has_attempt(student_id, scenario_id):
    """True when the student has ANY prior attempt (in-progress or completed):
    start-by-URL stays open for resumption even if the scenario is no longer
    eligible (game states are durable; see design §3.5)."""
    try:
        return bool(models.list_scenario_attempts(student_id, scenario_id=scenario_id, limit=1))
    except Exception:
        return False


def availability_reason(student):
    """Role/profile-driven reason for an empty library (never 'no content')."""
    target = (student.get("target_role") or {}).get("title") or ""
    if not target:
        return "Add skills to your profile (upload a CV) and choose a target role to see practice scenarios matched to you."
    return f"No practice scenarios are available for {target} yet — role-specific practice is being prepared."


def _gap_names(student):
    role = student.get("target_role")
    if not role:
        return []
    try:
        return [r["skill_name"].lower().strip() for r in matching.categorize(student, role) if r["status"] != "strong"]
    except Exception:
        return []


def list_scenarios(student):
    """Full catalog with per-scenario progress for a student + practice stats."""
    if not student:
        raise ValueError("Student required")
    student_id = student["id"]
    attempts = models.list_scenario_attempts(student_id, limit=200)

    # effective catalog = every authored scenario + this student's role-blueprint clones
    catalog = SCENARIOS + _blueprints_for(student)

    by_scenario = {}
    for scn in catalog:
        by_scenario[scn["id"]] = {"status": "not_started", "best_score": None, "attempts_count": 0, "last_outcome_title": None, "last_outcome_tone": None}

    completed = []
    skill_scores_by_name = {}
    practice_minutes = 0
    for a in attempts:
        sid = a["scenario_id"]
        if sid not in by_scenario:
            continue
        if a["status"] == "in_progress":
            if by_scenario[sid]["status"] == "not_started" or a["id"] > by_scenario[sid].get("_latest_id", 0):
                by_scenario[sid]["status"] = "in_progress"
                by_scenario[sid]["_latest_id"] = a["id"]
        else:
            by_scenario[sid]["attempts_count"] += 1
            scn = _scenario(sid)
            if scn:
                practice_minutes += int(scn.get("estimated_minutes") or 10)
            if a["score"] is not None and (by_scenario[sid]["best_score"] is None or a["score"] > by_scenario[sid]["best_score"]):
                by_scenario[sid]["best_score"] = round(a["score"])
            fb = a.get("feedback") or {}
            if fb.get("outcome_title"):
                by_scenario[sid]["last_outcome_title"] = fb["outcome_title"]
                by_scenario[sid]["last_outcome_tone"] = fb.get("outcome_tone")
            completed.append(a)
            for name, pct in (a.get("skill_scores") or {}).items():
                if pct is not None and pct > skill_scores_by_name.get(name, 0):
                    skill_scores_by_name[name] = pct
    for sid in by_scenario:
        by_scenario[sid].pop("_latest_id", None)
        if by_scenario[sid]["attempts_count"] and by_scenario[sid]["status"] == "not_started":
            by_scenario[sid]["status"] = "completed"

    avg = round(sum(a["score"] or 0 for a in completed) / len(completed)) if completed else None
    stats = {
        "scenarios_completed": len({a["scenario_id"] for a in completed}),
        "attempts": len(completed),
        "average_score": avg,
        "practice_time_minutes": practice_minutes,
        "skills_practiced": len(skill_scores_by_name),
    }

    gaps = _gap_names(student)
    eligible = [scn for scn in catalog if scenario_eligible(student, scn)]
    ranked = _rank_scenarios(student, eligible, gaps, attempts)
    recommended = [scn["id"] for scn in ranked]

    # Categories are derived from what is actually available so the library
    # never offers an empty facet (PHASES stay static — see design §3.3).
    derived_categories = [
        c for c in CATEGORIES if any(scn.get("category") == c["key"] for scn in eligible)
    ]
    availability = "ok" if eligible else "none"

    return {
        "scenarios": [public_scenario_card(scn, by_scenario[scn["id"]]) for scn in ranked],
        "availability": availability,
        "availability_reason": availability_reason(student),
        "recommended": recommended,
        "categories": derived_categories,
        "stats": stats,
        "target_role": (student.get("target_role") or {}).get("title") or None,
        "note": "Practice simulations prepare you for real situations. They build practice confidence — they never verify skills, which always requires the Assessment.",
    }


def scenario_history(student):
    """Per-attempt history for the Practice page: attempt date/version/score
    plus the scenario's role and family context, newest first."""
    if not student:
        return {"attempts": []}
    student_id = student["id"]
    rows = []
    for a in models.list_scenario_attempts(student_id, limit=200):
        scn = _scenario(a["scenario_id"])
        if not scn:
            continue
        fb = a.get("feedback") or {}
        diff = DIFFICULTIES.get(scn.get("difficulty"), DIFFICULTIES["beginner"])
        fam = scn.get("family")
        rows.append({
            "attempt_id": a["id"],
            "scenario_id": scn["id"],
            "title": scn.get("title") or scn["id"],
            "role_title": scn.get("role_title") or "",
            "family": fam,
            "family_label": scenario_catalog.FAMILY_LABEL_OF.get(fam),
            "family_icon": scenario_catalog.FAMILY_ICON_OF.get(fam),
            "difficulty_label": diff["label"],
            "difficulty_icon": diff["icon"],
            "status": a["status"],
            "score": round(a["score"]) if a["score"] is not None else None,
            "scenario_version": a.get("scenario_version") or scn.get("version") or scenario_catalog.SCENARIO_VERSION,
            "hints_used": a.get("hints_used") or 0,
            "started_at": a.get("started_at"),
            "completed_at": a.get("completed_at"),
            "outcome_title": fb.get("outcome_title"),
            "outcome_tone": fb.get("outcome_tone"),
        })
    rows.sort(key=lambda r: (r.get("started_at") or ""), reverse=True)
    return {"attempts": rows}


def _rank_scenarios(student, candidate_scenarios, gaps, attempts):
    """Recommendation order: tier 0 exact role-title match → tier 1 family →
    tier 2 skill overlap → tier 3 difficulty/progress (guide §4.1-4.2).
    Deterministic within a tier: difficulty, then unstarted, then title."""
    target = ((student.get("target_role") or {}).get("title") or "").strip()
    target_l = target.lower()
    fam = family_for_role(target) if target else None
    done_ids = {a["scenario_id"] for a in attempts if a["status"] == "completed"}
    diff_order = {"beginner": 0, "intermediate": 1, "advanced": 2}
    scored = []
    for scn in candidate_scenarios:
        scn_l = (scn.get("role_title") or "").strip().lower()
        if target and scn_l == target_l:
            tier = 0
        elif target and scn.get("family") == "generic" and scn.get("role_title") == target:
            tier = 0
        elif fam and scn.get("family") == fam:
            tier = 1
        else:
            sks = [s.lower().strip() for s in (scn.get("skills") or [])]
            overlap_gap = sum(1 for g in gaps if g in sks)
            overlap_profile = _skill_overlap(student, sks)
            tier = 2 if (overlap_gap or overlap_profile) else 3
        scored.append((
            tier,
            diff_order.get(scn.get("difficulty"), 1),
            0 if scn["id"] in done_ids else 1,  # prefer unstarted within a tier
            scn["title"].lower(),
            scn,
        ))
    scored.sort(key=lambda t: (t[0], t[1], -t[2], t[3]))
    return [t[-1] for t in scored]


# --------------------------------------------------------------- attempt state

def _new_state(scenario):
    return {
        "step_id": scenario["start_step"],
        "visited": [scenario["start_step"]],
        "decision_log": [],
        "evidence_viewed": [],
        "hints": [],
        "outcome": None,
    }


def start_scenario(student_id, scenario_id):
    student = models.get_student(student_id)
    scenario = _scenario(scenario_id)
    if not scenario:
        raise KeyError(scenario_id)
    existing = models.find_in_progress_scenario(student_id, scenario_id)
    if existing:
        return existing, scenario
    attempt = models.create_scenario_attempt(
        student_id, scenario_id, _new_state(scenario),
        scenario_version=scenario.get("version") or scenario_catalog.SCENARIO_VERSION,
    )
    return attempt, scenario


def _hint_policy(used):
    return {
        "penalty": HINT_PENALTY,
        "cap": HINT_PENALTY_CAP,
        "used": used or 0,
        "deduction": min(HINT_PENALTY_CAP, (used or 0) * HINT_PENALTY),
    }


def player_view(attempt, scenario, student=None):
    """Public step payload for the current state of an attempt.

    ``student`` is optional (looked up when omitted) and only used to surface
    the target-role heading the Phase 4 player requires. ``last_decision`` is
    the most-recent decision + its professional reasoning so the player can
    explain consequences right after each submission (never before one)."""
    if student is None:
        try:
            student = models.get_student(attempt.get("student_id"))
        except Exception:
            student = None
    state = attempt.get("state") or {}
    step_id = state.get("step_id") or scenario["start_step"]
    step = _step(scenario, step_id)
    if not step:
        raise KeyError(step_id)
    order = [s["id"] for s in scenario["steps"]]
    idx = order.index(step_id) if step_id in order else 0
    seen_outcomes = bool(state.get("outcome"))
    decision_log = state.get("decision_log") or []
    last = decision_log[-1] if decision_log else None
    last_decision = None
    if last:
        last_decision = {
            "label": last.get("label", "Decision made"),
            "icon": last.get("icon"),
            "verdict": last.get("verdict", "neutral"),
            "good": last.get("verdict") == "good",
            "points": last.get("points", 0),
            "feedback": last.get("feedback", ""),
            "consequence": last.get("consequence", ""),
            "step_title": _step_title_for(scenario, last.get("step_id")),
        }
    return {
        "attempt_id": attempt["id"],
        "scenario_id": scenario["id"],
        "scenario_title": scenario.get("title") or "",
        "scenario_version": attempt.get("scenario_version") or scenario.get("version") or scenario_catalog.SCENARIO_VERSION,
        "family": scenario.get("family"),
        "family_label": scenario_catalog.FAMILY_LABEL_OF.get(scenario.get("family")),
        "family_icon": scenario_catalog.FAMILY_ICON_OF.get(scenario.get("family")),
        "target_role": (student.get("target_role") or {}).get("title") if student else None,
        "role_title": scenario.get("role_title") or "",
        "status": attempt["status"],
        "step": {
            "id": step_id,
            "index": idx + 1,
            "total": len(order),
            "title": step.get("title") or "",
            "phase": _phase_of(scenario, step_id),
            "phase_label": _phase_label(_phase_of(scenario, step_id)),
            "situation": step.get("situation") or "",
            "intro": scenario.get("intro") or "",
            "evidence": _evidence_payload(step),
            "decisions": _decision_payload(step),
            "multi": bool(step.get("multi")),
            "options": _multi_payload(step),
            "type": "multi" if step.get("multi") else "choice",
        },
        "progress": {
            "step_number": idx + 1,
            "total_steps": len(order),
            "current_phase": _phase_of(scenario, step_id),
            "phases": PHASES,
        },
        "last_decision": last_decision,
        "hint_policy": _hint_policy(len(state.get("hints") or [])),
        "outcome": state.get("outcome"),
    }


def hint_for(attempt, scenario, step_id=None, question=None):
    state = attempt.get("state") or {}
    sid = step_id or state.get("step_id") or scenario["start_step"]
    step = _step(scenario, sid)
    if not step:
        return {"hint": "Think about what evidence you have not inspected yet.", "source": "curated"}
    base = step.get("hint") or "Think about what the evidence is telling you before you decide."
    if question:
        # Keep this a safety-capped, non-answer nudge even when a question is asked.
        return {"hint": f"{base} Regarding \"{str(question)[:140]}\": stay curious, but decide using the evidence you can open above.", "source": "curated", "question": str(question)[:140]}
    return {"hint": base, "source": "curated"}


def mark_hint(attempt, scenario):
    """Record that the student asked for a hint on the current step."""
    state = dict(attempt.get("state") or {})
    step_id = state.get("step_id") or scenario["start_step"]
    hints = list(state.get("hints") or [])
    if step_id not in hints:
        hints.append(step_id)
    state["hints"] = hints
    models.update_scenario_attempt(attempt["id"], state_json=state, hints_used=len(hints))
    return models.get_scenario_attempt(attempt["student_id"], attempt["id"])


# ------------------------------------------------------------------ scoring

def _apply_decision(state, scenario, decision):
    state["decision_log"].append({
        "step_id": state["step_id"],
        "decision_id": decision["id"],
        "label": decision["label"],
        "icon": decision["icon"],
        "points": decision.get("points", 0),
        "component": decision.get("component", "decision_making"),
        "verdict": decision.get("verdict", "neutral"),
        "feedback": decision.get("feedback", ""),
        "consequence": decision.get("consequence", ""),
    })
    state["step_id"] = decision.get("next") or state["step_id"]


def _apply_multi(state, scenario, step, option_ids):
    selected = {o["id"]: o for o in step.get("options") or [] if o["id"] in option_ids}
    if not selected:
        raise ValueError("Select at least one option")
    earned = sum(o.get("points", 0) for o in selected.values())
    correct = [o["label"] for o in step.get("options") or [] if o.get("good")]
    wrong_picked = [o["label"] for o in selected.values() if not o.get("good")]
    missed = [o["label"] for o in step.get("options") or [] if o.get("good") and o["id"] not in option_ids]
    note = f"You flagged the suspicious events correctly ({', '.join(correct)})."
    if wrong_picked:
        note += f" {', '.join(wrong_picked)} look suspicious but are predictable noise."
    state["decision_log"].append({
        "step_id": state["step_id"],
        "decision_id": "multi",
        "label": "Identification: " + ("; ".join(o["label"] for o in selected.values())),
        "icon": "🧠",
        "points": earned,
        "component": step.get("component", "threat_analysis"),
        "verdict": "good" if earned > 0 and not wrong_picked else ("neutral" if earned > 0 else "bad"),
        "feedback": note,
        "consequence": "Event correlation is the bridge from noise to incidents." if wrong_picked or missed else "A clean identification keeps the incident fast and focused.",
    })
    state["step_id"] = step.get("after") or state["step_id"]


def _record_outcome(state, scenario, next):
    key = next.split(":", 1)[1]
    outcome = (scenario.get("outcomes") or {}).get(key)
    outcome = outcome or {"key": key, "title": key, "icon": "🏁", "tone": OUTCOME_BAD, "summary": ""}
    state["outcome"] = outcome
    state.pop("step_id", None)


def _component_totals(scenario, state):
    visited = set(state.get("visited") or [])
    total = {c: 0 for c in COMPONENTS}
    earned = {c: 0 for c in COMPONENTS}
    logged = {d["step_id"] for d in state.get("decision_log") or []}

    for step in scenario["steps"]:
        if step["id"] not in visited:
            continue
        if step.get("multi"):
            comp = step.get("component", "threat_analysis")
            total[comp] += sum(o.get("points", 0) for o in step.get("options") or [] if o.get("good"))
            entry = next((d for d in state["decision_log"] if d["step_id"] == step["id"]), None)
            if entry and step["id"] in logged:
                earned[comp] += max(0, entry["points"])
            continue
        decisions = step.get("decisions") or []
        if not decisions:
            continue
        best = max(decisions, key=lambda d: d.get("points", 0))
        total[best.get("component", "decision_making")] += best.get("points", 0)
        if step["id"] in logged:
            entry = next((d for d in state["decision_log"] if d["step_id"] == step["id"]), None)
            if entry:
                for d in decisions:
                    if d["id"] == entry["decision_id"]:
                        earned[d.get("component", "decision_making")] += d.get("points", 0)

    viewed = set(state.get("evidence_viewed") or [])
    for step in scenario["steps"]:
        if step["id"] not in visited:
            continue
        for e in step.get("evidence") or []:
            comp = e.get("component", "investigation")
            total[comp] += e.get("points", 0)
            if e["id"] in viewed:
                earned[comp] += e.get("points", 0)
    return total, earned


def _component_pcts(scenario, state):
    if not scenario:
        return {}, {}
    total, earned = _component_totals(scenario, state)
    pcts = {
        c: (round(earned[c] / total[c] * 100) if total[c] else None)
        for c in COMPONENTS
    }
    return pcts, total


def _overall(pcts, total, hints_used):
    weights = COMPONENT_WEIGHTS
    used = [c for c in COMPONENTS if total.get(c)]
    if not used:
        return 0
    wsum = sum(weights[c] for c in used)
    raw = sum((pcts[c] or 0) * weights[c] for c in used) / wsum
    penalty = min(HINT_PENALTY_CAP, (hints_used or 0) * HINT_PENALTY)
    return max(0, round(raw - penalty))


def _verdict(score):
    if score >= 85:
        return {"label": "Strong performance", "tone": "great"}
    if score >= GOOD_SCORE:
        return {"label": "Good performance", "tone": "good"}
    if score >= 50:
        return {"label": "Broadly reasonable", "tone": "fair"}
    return {"label": "Needs a closer look", "tone": "review"}


def decide(attempt, scenario, payload):
    """Advance an attempt by one decision (or multi-select). Returns (updated, completed)."""
    from .database import get_cursor
    if attempt["status"] == "completed":
        return attempt, True
    state = dict(attempt.get("state") or {})
    step_id = state.get("step_id") or scenario["start_step"]
    step = _step(scenario, step_id)
    if not step:
        raise KeyError(step_id)

    # merge newly viewed evidence into state before deciding
    viewed = list(state.get("evidence_viewed") or [])
    for eid in (payload or {}).get("evidence_viewed") or []:
        if eid not in viewed:
            viewed.append(eid)
    state["evidence_viewed"] = viewed

    if step.get("multi"):
        option_ids = (payload or {}).get("option_ids") or []
        _apply_multi(state, scenario, step, option_ids)
    else:
        decision_id = (payload or {}).get("decision_id") or ""
        decision = next((d for d in step.get("decisions") or [] if d["id"] == decision_id), None)
        if not decision:
            raise ValueError(f"Unknown decision: {decision_id}")
        _apply_decision(state, scenario, decision)

    completed = False
    nxt = state.get("step_id")
    if isinstance(nxt, str) and nxt.startswith("outcome:"):
        _record_outcome(state, scenario, nxt)
        completed = True

    # track visited steps transitively (the next step is now reachable)
    if not completed:
        nid = state.get("step_id")
        if nid and nid not in state["visited"]:
            state["visited"].append(nid)

    fields = {
        "state_json": state,
        "evidence_viewed_json": viewed,
        "decisions_json": state.get("decision_log") or [],
        "hints_used": len(state.get("hints") or []),
    }
    if completed:
        fields.update(complete_fields(scenario, state))
    models.update_scenario_attempt(attempt["id"], **fields)
    updated = models.get_scenario_attempt(attempt["student_id"], attempt["id"])
    return updated, completed


def complete_fields(scenario, state):
    """Everything that needs persisting when a scenario completes."""
    pcts, total = _component_totals(scenario, state)
    hints = len(state.get("hints") or [])
    score = _overall(pcts, total, hints)
    skill_scores = {
        name: (int(pcts.get(scenario["skills_components"].get(name, "investigation")))
               if pcts.get(scenario["skills_components"].get(name, "investigation")) is not None else None)
        for name in (scenario.get("skills") or [])
    }

    review = [
        {
            "step_title": _step_title_for(scenario, d["step_id"]),
            "decision": d["label"],
            "verdict": d["verdict"],
            "points": d["points"],
            "feedback": d["feedback"],
            "consequence": d["consequence"],
            "good": d["verdict"] == "good",
        }
        for d in (state.get("decision_log") or [])
    ]
    strengths = [d["decision"] for d in review if d["good"]][:4]
    if not strengths:
        strengths = ["You investigated the scenario and made a call under time pressure."]
    improvements = [d["feedback"] for d in review if d["verdict"] != "good"][:3]
    if hints:
        improvements.append(f"You used {hints} hint{'s' if hints > 1 else ''}; try deciding from the evidence first next time.")
    if pcts.get("investigation") is not None and pcts["investigation"] < 50 and len(state.get("decision_log") or []) >= 2:
        improvements.append("Inspect the available evidence tabs before deciding — they hold the details that justify your call.")

    outcome = state.get("outcome") or {}
    return {
        "status": "completed",
        "score": score,
        "skill_scores_json": skill_scores,
        "strengths_json": strengths,
        "improvements_json": improvements,
        "feedback_json": {
            "outcome_key": outcome.get("key"),
            "outcome_title": outcome.get("title"),
            "outcome_icon": outcome.get("icon"),
            "outcome_tone": outcome.get("tone"),
            "outcome_summary": outcome.get("summary"),
            "verdict_label": _verdict(score)["label"],
            "verdict_tone": _verdict(score)["tone"],
            "component_pcts": {k: (int(v) if v is not None else None) for k, v in pcts.items()},
            "skill_scores": skill_scores,
            "hints_used": hints,
        },
    }


def _step_title_for(scenario, step_id):
    step = _step(scenario, step_id)
    return (step or {}).get("title") or "Decision"


def improve_skill_confidence(student_id, scenario):
    """Practice performance upgrades a student's SELF-REPORTED confidence only.
    Returns [{name, before, after}]. Verified skills are never touched, and a
    skill the student never claimed is never invented."""
    attempts = [a for a in models.list_scenario_attempts(student_id, scenario["id"]) if a["status"] == "completed"]
    if not attempts:
        return []
    best = max(attempts, key=lambda a: a["score"] or 0)
    deltas = []
    for name, pct in (best.get("skill_scores") or {}).items():
        if pct is not None and pct >= GOOD_SCORE:
            delta = models.upgrade_self_reported_level(student_id, name)
            if delta:
                deltas.append(delta)
    return deltas


def _skill_for_component(scenario, component):
    """First scenario skill whose ``skills_components`` maps onto a competency
    component (used to connect weak competencies to existing learning content)."""
    for skill_name, comp in (scenario.get("skills_components") or {}).items():
        if comp == component:
            return skill_name
    return None


def _follow_up(scenario, attempt):
    """Phase 4 requirement: results connect the weakest competency to an
    existing learning/practice follow-up. The weakest component is chosen from
    the persisted component percentages; the related scenario skill (when one
    maps to it) becomes the learning target."""
    fb = attempt.get("feedback") or {}
    pcts = fb.get("component_pcts") or {}
    labels = scenario_catalog.family_component_labels(scenario.get("family") or "")
    scored = [(c, pcts[c]) for c in COMPONENTS if pcts.get(c) is not None]
    base = {
        "component_key": None,
        "component_label": None,
        "weakness_pct": None,
        "skill": None,
        "skill_id": None,
        "action": "practice",
    }
    if not scored:
        base["message"] = "Replay this scenario and inspect every evidence tab before deciding to sharpen the same calls."
        return base
    key, pct = min(scored, key=lambda kv: kv[1])
    label = labels.get(key) or COMPONENT_LABELS.get(key) or key.title().replace("_", " ")
    skill = _skill_for_component(scenario, key)
    skill_id = None
    if skill:
        try:
            row = models.get_skill_by_name(skill)
            skill_id = row.get("id") if row else None
        except Exception:
            skill_id = None
    is_weak = pct is not None and pct < 50
    if skill_id and is_weak:
        action = "lesson"
        message = f"Your weakest competency here was {label} at {pct}%. Review the {skill} learning content for that competency before your next attempt."
    elif skill:
        action = "practice"
        message = f"Your weakest competency here was {label} at {pct}%. Replay the scenario and focus your evidence review on that area next time."
    else:
        action = "practice"
        message = f"Your weakest competency here was {label} at {pct}%. Replay and inspect the evidence before deciding to build it up."
    base.update({
        "component_key": key,
        "component_label": label,
        "weakness_pct": int(pct) if pct is not None else None,
        "skill": skill,
        "skill_id": skill_id,
        "action": action,
        "message": message,
    })
    return base


def result_payload(attempt, scenario, match_before=None, match_after=None, deltas=None, student=None):
    deltas = deltas or []
    if student is None:
        try:
            student = models.get_student(attempt.get("student_id"))
        except Exception:
            student = None
    fb = attempt.get("feedback") or {}
    pcts = fb.get("component_pcts") or {}
    labels = _component_label_map(scenario)
    return {
        "completed": True,
        "attempt_id": attempt["id"],
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "scenario_version": attempt.get("scenario_version") or scenario.get("version") or scenario_catalog.SCENARIO_VERSION,
        "family": scenario.get("family"),
        "family_label": scenario_catalog.FAMILY_LABEL_OF.get(scenario.get("family")),
        "family_icon": scenario_catalog.FAMILY_ICON_OF.get(scenario.get("family")),
        "target_role": (student.get("target_role") or {}).get("title") if student else None,
        "role_title": scenario.get("role_title") or "",
        "difficulty_icon": DIFFICULTIES.get(scenario.get("difficulty"), DIFFICULTIES["beginner"])["icon"],
        "difficulty_label": DIFFICULTIES.get(scenario.get("difficulty"), DIFFICULTIES["beginner"])["label"],
        "score": round(attempt.get("score") or 0),
        "verdict_label": fb.get("verdict_label"),
        "verdict_tone": fb.get("verdict_tone"),
        "outcome": {
            "key": fb.get("outcome_key"),
            "title": fb.get("outcome_title"),
            "icon": fb.get("outcome_icon"),
            "tone": fb.get("outcome_tone"),
            "summary": fb.get("outcome_summary"),
        },
        "components": [
            {"key": k, "label": labels[k], "pct": pcts.get(k)}
            for k in COMPONENTS
        ],
        "skills": [
            {"name": k, "pct": v}
            for k, v in (fb.get("skill_scores") or {}).items()
        ],
        "skills_updated": deltas,
        "match": {
            "before": match_before,
            "after": match_after,
            "delta": (match_after - match_before) if (match_before is not None and match_after is not None) else None,
        },
        "decision_review": _decision_review_from_state(attempt.get("state") or {}, scenario),
        "strengths": attempt.get("strengths") or [],
        "improvements": attempt.get("improvements") or [],
        "hints_used": attempt.get("hints_used") or fb.get("hints_used") or 0,
        "hint_policy": _hint_policy(attempt.get("hints_used") or fb.get("hints_used") or 0),
        "follow_up": _follow_up(scenario, attempt),
        "evidence_inspected_pct": pcts.get("investigation"),
        "certified": False,
        "note": "Practice performance builds practice confidence in your profile, but it never verifies a skill — verified skills always require the Assessment system.",
    }


def _decision_review_from_state(state, scenario):
    rows = []
    for d in state.get("decision_log") or []:
        step = _step(scenario, d["step_id"])
        rows.append({
            "step_title": (step or {}).get("title") or "Decision",
            "decision": d["label"],
            "icon": d["icon"],
            "verdict": d["verdict"],
            "good": d["verdict"] == "good",
            "feedback": d["feedback"],
            "consequence": d["consequence"],
        })
    return rows